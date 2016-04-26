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
        return RoleYaml.query.all()

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


class Classes(Resource):
    @marshal_with(models_templates)
    def get(self, **kwargs):
        return ClassYaml.query.all()


class ClassDetails(Resource):
    def get(self, class_id, **kwargs):
        cls = ClassYaml.query.get(class_id)
        content = json.loads(cls.content)
        body = [{'id': cls.id}]
        params = []
        for key in content:
            elements = {'name': key, 'value': content[key]['value'], 'type': content[key]['type'],
                            'options': {'lable': content[key]['lable'], }}
            params.append(elements)
        body.append({'fields': params})
        return body, 200


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
                classes.append(ClassYaml.query.filter_by(name=key).first())
            content = json.dumps(data)
            role = RoleYaml(name, el, content, classes)
            db.session.add(role)
            db.session.commit()
        for el in removed_files:
            role = RoleYaml.query.filter_by(file_name=el).first()
            db.session.delete(role)
            db.session.commit()
        for el in modified_files:
            data = self._from_yaml_to_dict(el)
            role = RoleYaml.query.filter_by(file_name=el).first()
            role.classes = []
            for key in data:
                role.classes.append(ClassYaml.query.filter_by(name=key).first())
            role.content = json.dumps(data)
            db.session.commit()

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


api.add_resource(GitHook, '/repository')
api.add_resource(Roles, '/roles')
api.add_resource(Classes, '/classes')
api.add_resource(ClassDetails, '/classes/<class_id>')
api.add_resource(RoleDetails, '/roles/<role_id>')


def create_classes():
    db.create_all()
    with open(config['REPOSITORY_PATH'] + '/classes/apache.yaml') as file:
        data = yaml.safe_load(file)
    file.close()
    content = json.dumps(data)
    apache = ClassYaml('apache', 'apache.yaml', content)
    with open(config['REPOSITORY_PATH'] + '/classes/ntp.yaml') as file:
        data = yaml.safe_load(file)
    file.close()
    content = json.dumps(data)
    ntp = ClassYaml('ntp', 'ntp.yaml', content)
    with open(config['REPOSITORY_PATH'] + '/classes/mysql_server.yaml') as file:
        data = yaml.safe_load(file)
    file.close()
    content = json.dumps(data)
    mysql = ClassYaml('mysql_server', 'mysql_server.yaml', content)

    db.session.add_all([apache, ntp, mysql])
    db.session.commit()

if __name__ == '__main__':
    app.run(host=config['HOST'])