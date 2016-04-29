import yaml
import json
import os
import copy
import re
from git import Repo
from flask import Flask
from flask import request
from flask_restful import Resource
from flask_restful import Api
from flask_restful import fields
from flask_restful import marshal_with
from flask_restful import reqparse
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import JSON


# configuration
app = Flask(__name__)
app.config.from_object('local_settings.Config')
config = app.config
db = SQLAlchemy(app)
api = Api(app)

models_templates = {
    'id': fields.String,
    'name': fields.String,
}

parser = reqparse.RequestParser()
parser.add_argument('name')


class Roles(Resource):
    @marshal_with(models_templates)
    def get(self, **kwargs):
        return Role.query.all()

    @marshal_with(models_templates)
    def post(self, **kwargs):
        data = request.get_json()
        role = Role(data['name'], None)
        db.session.add(role)
        db.session.commit()
        return Role.query.get(role.id), 201

    def put(self, role_id, **kwargs):
        role = Role.query.get_or_404(role_id)
        data = request.get_json()
        data_map = {}
        for el in data:
            data_map[el] = {}
            fields_copy = copy.copy(data[el]['fields'])
            for key in fields_copy:
                if key == 'custom':
                    data[el]['fields'].pop(key)
                    if len(fields_copy['custom']) != 0:
                        value = fields_copy[key]
                        matches = re.findall(r'(\w+):\s*(\d+)', value)
                        matches = map(lambda x: (x[0], int(x[1])), matches)
                        custom_fields = dict(matches)
                        data_map[el].update(custom_fields)
            data_map[el].update(data[el]['fields'])
        file_name = 'roles/' + role.name + '.yaml'
        with open(config['REPOSITORY_PATH'] + '/' + file_name, 'w+') as file:
            yaml.safe_dump(data_map, file, default_flow_style=False)
        file.close()
        repository = Repo(config['REPOSITORY_PATH'])
        index = repository.index
        index.add([config['REPOSITORY_PATH'] + '/' + file_name])
        index.commit('update role: ' + role.name)
        repository.remotes.origin.push()
        role.file_name = file_name
        classes = []
        for key in data_map:
            cls = Class(key, json.dumps(data_map[key]), Template.query.filter_by(name=key).first())
            db.session.add(cls)
            classes.append(cls)
        if role.classes is not None:
            for el in role.classes:
                db.session.delete(el)
            db.session.commit()
        role.classes = classes
        db.session.commit()
        return role.id, 200


class Classes(Resource):
    @marshal_with(models_templates)
    def post(self, role_id, template_id):
        role = Role.query.get_or_404(role_id)
        template = Template.query.get_or_404(template_id)
        cls_content = {}
        template_content = json.loads(template.content)
        for key in template_content:
            cls_content[key] = template_content[key]['options']['initial']
        cls = Class(template.name, json.dumps(cls_content), template)
        db.session.add(cls)
        if role.classes is None:
            role.classes = []
        role.classes.append(cls)
        db.session.commit()
        return cls, 201

    def delete(self, class_id, **kwargs):
        cls = Class.query.get_or_404(class_id)
        db.session.delete(cls)
        db.session.commit()
        return 204


class ClassDetails(Resource):
    def get(self, role_id, **kwargs):
        role = Role.query.get_or_404(role_id)
        cls = role.classes
        response = []
        for el in cls:
            params = {'name': el.name, 'id': el.id, 'fields': []}
            cls_content = json.loads(el.content)
            cls_content_copy = copy.copy(cls_content)
            template_content = el.templates.content
            for it in cls_content:
                fields = {'name': it, 'value': cls_content[it]}
                d = json.loads(template_content)
                if it in d:
                    fields['name'] = it
                    fields['type'] = d[it]['type']
                    fields['options'] = d[it]['options']
                    params['fields'].append(fields)
                    cls_content_copy.pop(it)
            custom_field = {'name': 'custom',
                            'type': 'text',
                            'options': {'label': 'custom'}}
            values = ['{}: {}'.format(k, v) for k, v in cls_content_copy.iteritems()]
            custom_field['value'] = '\n'.join(values)
            params['fields'].append(custom_field)
            app.logger.debug(cls_content_copy)
            response.append(params)
        return response, 200


class Templates(Resource):
    @marshal_with(models_templates)
    def get(self, **kwargs):
        return Template.query.all()


class GitHook(Resource):
    def _from_yaml_to_dict(self, file_name):
        with open(config['REPOSITORY_PATH'] + '/' + file_name) as file:
                data = yaml.safe_load(file)
        file.close()
        return data

    def _get_role_name(self, file_name):
        name = file_name.split('/')
        name = os.path.splitext(name[1])[0]
        return name

    def post(self):
        added_files = []
        removed_files = []
        modified_files = []
        commits = request.get_json()['commits']
        for el in commits:
            added_files.extend(el['added'])
            removed_files.extend(el['removed'])
            modified_files.extend(el['modified'])

        repository = Repo(config['REPOSITORY_PATH'])
        origin = repository.remotes.origin
        origin.pull()

        for el in added_files:
            data = self._from_yaml_to_dict(el)
            name = self._get_role_name(el)
            role = Role.query.filter_by(name=name).first()
            if role is None:
                role = Role(name, el)
                classes = []
                for key in data:
                    cls = Class(key, json.dumps(data[key]), Template.query.filter_by(name=key).first())
                    db.session.add(cls)
                    db.session.commit()
                    classes.append(cls)
                role.classes = classes
                db.session.add(role)
                db.session.commit()
        for el in removed_files:
            name = self._get_role_name(el)
            role = Role.query.filter_by(name=name)
            db.session.delete(role)
            db.session.commit()
        for el in modified_files:
            name = self._get_role_name(el)
            role = Role.query.filter_by(name=name).first()
            data = self._from_yaml_to_dict(el)
            classes = role.classes
            for cls in classes:
                db.session.delete(cls)
            db.session.commit()
            classes = []
            for key in data:
                cls = Class(key, json.dumps(data[key]), Template.query.filter_by(name=key).first())
                db.session.add(cls)
                classes.append(cls)
            role.classes = classes
            db.session.commit()

        app.logger.debug([el.name for el in Role.query.all()])
        return request.get_json(), 200


class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(54), unique=True, nullable=False)
    file_name = db.Column(db.String(54), unique=True, nullable=True)
    classes = db.relationship('Class', backref='role', lazy='dynamic')

    def __init__(self, name, file_name):
        self.name = name
        self.file_name = file_name


class Class(db.Model):
    __tablename__ = 'classes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(54), nullable=False)
    content = db.Column(JSON, nullable=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'))
    template_id = db.Column(db.Integer, db.ForeignKey('templates.id'))
    templates = db.relationship('Template', backref='class', uselist=False)

    def __init__(self, name, content, templates):
        self.name = name
        self.content = content
        self.templates = templates


class Template(db.Model):
    __tablename__ = 'templates'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(54), unique=True, nullable=False)
    file_name = db.Column(db.String(54), nullable=True)
    content = db.Column(JSON, nullable=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'))

    def __init__(self, name, file_name, content):
        self.name = name
        self.file_name = file_name
        self.content = content

api.add_resource(GitHook, '/repository')
api.add_resource(Roles, '/roles', '/roles/<role_id>')
api.add_resource(Templates, '/templates')
api.add_resource(Classes, '/roles/<role_id>/add_class/<template_id>', '/classes/<class_id>')
api.add_resource(ClassDetails, '/roles/<role_id>/classes')


def create_templates():
    db.create_all()
    with open(config['REPOSITORY_PATH'] + '/classes/apache.yaml') as file:
        data = yaml.safe_load(file)
    file.close()
    content = json.dumps(data)
    apache = Template('apache', 'apache.yaml', content)
    with open(config['REPOSITORY_PATH'] + '/classes/ntp.yaml') as file:
        data = yaml.safe_load(file)
    file.close()
    content = json.dumps(data)
    ntp = Template('ntp', 'ntp.yaml', content)
    with open(config['REPOSITORY_PATH'] + '/classes/mysql_server.yaml') as file:
        data = yaml.safe_load(file)
    file.close()
    content = json.dumps(data)
    mysql = Template('mysql_server', 'mysql_server.yaml', content)

    db.session.add_all([apache, ntp, mysql])
    db.session.commit()

if __name__ == '__main__':
    app.run(host=config['HOST'])
