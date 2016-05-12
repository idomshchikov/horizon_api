import yaml
import json
import os
import copy
import re
import collections
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


def _subs_str(s):
    res = re.sub(r':', ': ', s)
    return re.sub(':\s+', ': ', res)


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
        data_map = {'classes': data.keys()}
        content = {}
        for el in data:
            content[el] = {}
            fields_copy = copy.copy(data[el]['fields'])
            custom_value = fields_copy['custom']
            data[el]['fields'].pop('custom')
            if len(custom_value) != 0:
                custom_value = _subs_str(custom_value)
                custom_fields = yaml.safe_load(custom_value)
                content[el].update(custom_fields)
                for item in custom_fields:
                    data_map[el+'::'+item] = custom_fields[item]
            content[el].update(data[el]['fields'])
            app.logger.debug(data[el]['fields'])
            fields = data[el]['fields']
            for key in fields:
                data_map[el+'::'+key] = fields[key]
        app.logger.debug(content)
        app.logger.debug(data_map)
        file_name = 'roles/' + role.name + '.yaml'

        with open(config['REPOSITORY_PATH'] + '/' + file_name, 'w+') as file:
            yaml.safe_dump(data_map, file,  explicit_start=True, default_flow_style=False)
        file.close()
        repository = Repo(config['REPOSITORY_PATH'])
        index = repository.index
        index.add([config['REPOSITORY_PATH'] + '/' + file_name])
        index.commit('update role: ' + role.name)
        repository.remotes.origin.push()
        role.file_name = file_name
        classes = []
        for key in content:
            cls = Class(key, json.dumps(content[key]), Template.query.filter_by(name=key).first())
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

    def _parse_key(self, key):
        res = key.split('::')
        res.pop(-1)
        app.logger.debug(res)
        if len(res) > 1:
            res = '::'.join()

            return res
        app.logger.debug(res)
        return res[0]

    def _parse_prop(self, key):
        res = key.split('::')
        return res.pop(-1)

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
        repository.git.stash('save')
        origin.pull()
        #repository.git.stash('pop')

        for el in added_files:
            data = self._from_yaml_to_dict(el)
            name = self._get_role_name(el)
            role = Role.query.filter_by(name=name).first()
            if role is None:
                role = Role(name, el)
                classes = []
                del data['classes']
                od = collections.OrderedDict(sorted(data.items()))
                content = {}
                for key in od:
                    app.logger.debug(key)
                    parsed_key = self._parse_key(key)
                    if parsed_key not in content:
                        content[parsed_key] = {}
                    parsed_prop = self._parse_prop(key)
                    prop_dic = {parsed_prop: data[key]}
                    content[parsed_key].update(prop_dic)
                app.logger.debug(content)
                for key in content:
                    app.logger.debug(key)
                    cls = Class(key, json.dumps(content[key]), Template.query.filter_by(name=key).first())
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
            role = Role.query.filter_by(name=name).first_or_404()
            data = self._from_yaml_to_dict(el)
            classes = role.classes
            for cls in classes:
                db.session.delete(cls)
            db.session.commit()
            classes = []
            del data['classes']
            od = collections.OrderedDict(sorted(data.items()))
            content = {}
            for key in od:
                app.logger.debug(key)
                parsed_key = self._parse_key(key)
                if parsed_key not in content:
                    content[parsed_key] = {}
                parsed_prop = self._parse_prop(key)
                prop_dic = {parsed_prop: data[key]}
                content[parsed_key].update(prop_dic)
            app.logger.debug(content)
            for key in content:
                cls = Class(key, json.dumps(content[key]), Template.query.filter_by(name=key).first())
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

    with open(config['REPOSITORY_PATH'] + '/classes/mysql.yaml') as file:
        data = yaml.safe_load(file)
    file.close()
    content = json.dumps(data)
    mysql = Template('mysql', 'mysql.yaml', content)

    with open(config['REPOSITORY_PATH'] + '/classes/haproxy.yaml') as file:
        data = yaml.safe_load(file)
    file.close()
    content = json.dumps(data)
    haproxy = Template('haproxy', 'haproxy.yaml', content)

    with open(config['REPOSITORY_PATH'] + '/classes/java.yaml') as file:
        data = yaml.safe_load(file)
    file.close()
    content = json.dumps(data)
    java = Template('java', 'java.yaml', content)

    with open(config['REPOSITORY_PATH'] + '/classes/postgresql.yaml') as file:
        data = yaml.safe_load(file)
    file.close()
    content = json.dumps(data)
    postgresql = Template('postgresql', 'postgresql.yaml', content)

    with open(config['REPOSITORY_PATH'] + '/classes/rabbitmq.yaml') as file:
        data = yaml.safe_load(file)
    file.close()
    content = json.dumps(data)
    rabbitmq = Template('rabbitmq', 'rabbitmq.yaml', content)

    db.session.add_all([apache, ntp, mysql, haproxy, java, postgresql, rabbitmq])
    db.session.commit()

if __name__ == '__main__':
    app.run(host=config['HOST'])
