# all the imports
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
SECRET_KEY = 'development key'
REPOSITORY_PATH = '/Users/maestro/Documents/work/temp_git'
DEBUG = True
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg2://postgres:@localhost/horizondb'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config.from_object(__name__)
db = SQLAlchemy(app)
api = Api(app)


roles_json_templates = {
    'id': fields.String,
    'name': fields.String,
}


class Roles(Resource):
    @marshal_with(roles_json_templates)
    def get(self, **kwargs):
        return RoleYaml.query.all()

    def post(self, *kwargs):
        return 201


class RoleDetails(Resource):
        def get(self, role_id, **kwargs):
            role = RoleYaml.query.get(role_id)
            responce_body = []
            params = []
            for item in role.classes:
                yamls = {}
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
            return 201


class GitHook(Resource):

    def _from_yaml_to_dict(self, file_name):
        with open(REPOSITORY_PATH + '/' + file_name) as file:
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

        repository = Repo(REPOSITORY_PATH)
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
api.add_resource(RoleDetails, '/roles/<role_id>')


def create_classes():
    db.create_all()
    with open(REPOSITORY_PATH + '/classes/apache.yaml') as file:
        data = yaml.safe_load(file)
    file.close()
    content = json.dumps(data)
    apache = ClassYaml('apache', 'apache.yaml', content)
    with open(REPOSITORY_PATH + '/classes/ntp.yaml') as file:
        data = yaml.safe_load(file)
    file.close()
    content = json.dumps(data)
    ntp = ClassYaml('ntp', 'ntp.yaml', content)
    with open(REPOSITORY_PATH + '/classes/mysql_server.yaml') as file:
        data = yaml.safe_load(file)
    file.close()
    content = json.dumps(data)
    mysql = ClassYaml('mysql_server', 'mysql_server.yaml', content)

    db.session.add_all([apache, ntp, mysql])
    db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)