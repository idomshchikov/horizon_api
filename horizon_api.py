import yaml
import json
import os
from git import Repo
from flask import Flask
from flask import request
from flask_restful import Resource
from flask_restful import Api
from flask_restful import fields
from flask_restful import marshal_with
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


class Roles(Resource):
    @marshal_with(models_templates)
    def get(self, **kwargs):
        return Role.query.all()

    def post(self, **kwargs):
        data = request.get_json()
        with open(config['REPOSITORY_PATH'] + '/roles/', 'w+') as file:
            yaml.dump(data, file)
        file.close()
        repository = Repo(config['REPOSITORY_PATH'])
        index = repository.index
        untracked_files = repository.untracked_files
        for el in untracked_files:
            index.add(el)
        index.commit('new role file')
        origin = repository.remotes.origin
        origin.push()
        classes = []
        for key in data:
                classes.append(ClassYaml.query.filter_by(name=key).first())
        role = RoleYaml('name', 'file.name', data, classes)
        id = db.session.add(role)
        db.session.commit()
        return id, 201


class ClassDetails(Resource):
    def get(self, role_id, **kwargs):
        role = Role.query.get(role_id)
        cls = role.classes
        templates = role.templates
        response = []
        for el in cls:
            params = {}
            params['name'] = el.name
            params['id'] = el.id
            params['fields'] = []
            cls_content = json.loads(el.content)
            for el in cls_content:
                fields = {'name': el, 'value': cls_content[el]}
                params['fields'].append(fields)
            response.append(params)
        return response, 200


class Classes(Resource):
    def get(self, **kwargs):

        return 200


class RoleDetails(Resource):
    def get(self, role_id, **kwargs):
        role = RoleYaml.query.get(role_id)
        responce_body = []
        for item in role.classes:
            yamls = {}
            params = []
            data = json.loads(item.content)
            for key in data:
                elements = {'name': key, 'value': data[key]['value'], 'type': data[key]['type'],
                            'options': {'lable': data[key]['lable'], }}
                params.append(elements)
            yamls['name'] = item.name
            yamls['fields'] = params
            responce_body.append(yamls)
        return responce_body, 200

    def put(self, role_id, **kwargs):
        data = request.get_json()
        role = RoleYaml.query.get(role_id)
        with open(config['REPOSITORY_PATH'] + '/roles/', 'w+') as file:
            yaml.dump(data, file)
        file.close()
        role.content = data
        role.classes = []
        db.session.commit()
        return role.id, 200


class GitHook(Resource):
    def _from_yaml_to_dict(self, file_name):
        with open(config['REPOSITORY_PATH'] + '/' + file_name) as file:
                data = yaml.safe_load(file)
        file.close()
        return data

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
            name = el.split('/')
            name = os.path.splitext(name[1])[0]
            classes = []
            for key in data:
                cls = Class(key, json.dumps(data[key]), Template.query.filter_by(name=key))
                db.session.add(cls)
                db.session.commit()
                classes.append(cls)
            role = Role(name, el, classes)
            db.session.add(role)
            db.session.commit()
        for el in removed_files:
            pass
        for el in modified_files:
           pass

        app.logger.debug([el.name for el in RoleYaml.query.all()])
        return request.get_json(), 200


class RoleYaml(db.Model):
    __tablename__ = 'role_yamls'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(54), unique=True, nullable=False)
    file_name = db.Column(db.String(54), unique=True, nullable=True)
    content = db.Column(JSON, nullable=True)
    classes = db.relationship('ClassYaml', backref='roles', lazy='dynamic')

    def __init__(self, name, file_name, content, classes):
        self.name = name
        self.file_name = file_name
        self.content = content
        self.classes = classes


class ClassYaml(db.Model):
    __tablename__ = 'class_yamls'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(54), unique=True, nullable=False)
    file_name = db.Column(db.String(54), nullable=True)
    content = db.Column(JSON, nullable=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role_yamls.id'))

    def __init__(self, name, file_name, content):
        self.name = name
        self.file_name = file_name
        self.content = content


class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(54), unique=True, nullable=False)
    file_name = db.Column(db.String(54), unique=True, nullable=True)
    classes = db.relationship('Class', backref='role', lazy='dynamic')

    def __init__(self, name, file_name, classes):
        self.name = name
        self.file_name = file_name
        self.classes = classes


class Class(db.Model):
    __tablename__ = 'classes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(54), unique=True, nullable=False)
    content = db.Column(JSON, nullable=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'))
    templates = db.relationship('Template', backref='class', lazy='dynamic')

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
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'))

    def __init__(self, name, file_name, content):
        self.name = name
        self.file_name = file_name
        self.content = content

api.add_resource(GitHook, '/repository')
api.add_resource(Roles, '/roles')
api.add_resource(Classes, '/classes')
api.add_resource(ClassDetails, '/roles/<role_id>/classes')
api.add_resource(RoleDetails, '/roles/<role_id>')


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
