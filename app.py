from flask import Flask
from flask_restx import Resource, Api, fields, reqparse
import requests
import subprocess
import os

app = Flask(__name__)
api = Api(app, version='1.0', title='Bitbucket Migration API', description='API for Bitbucket migration')

ns = api.namespace('Bitbucket', description='Bitbucket Migration')

project_fields = api.model('Project', {
    'project_name': fields.String,
    'repositories': fields.List(fields.String)
})
def list_projects(args):
    SERVER_URL = args['SERVER_URL']
    SERVER_TOKEN = args['SERVER_TOKEN']
    PROJECT_KEY = args.get('PROJECT_KEY')  
    headers_server = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {SERVER_TOKEN}'
    }

    try:
        all_projects_and_repos = []
        response_server = requests.get(f'{SERVER_URL}/rest/api/1.0/projects', headers=headers_server)
        response_server.raise_for_status()
        projects_data = response_server.json()

        for project in projects_data['values']:
            project_key = project['key']

            # Check if a specific project key is provided and filter by it
            if PROJECT_KEY is None or project_key == PROJECT_KEY:
                # Fetch repositories from the Bitbucket Server for each project
                response_server = requests.get(f'{SERVER_URL}/rest/api/1.0/projects/{project_key}/repos', headers=headers_server)
                response_server.raise_for_status()
                repositories_data = response_server.json()
                project_info = {
                    'project_name': project['name'],
                    'repositories': [repo['name'] for repo in repositories_data['values']]
                }
                all_projects_and_repos.append(project_info)

        return all_projects_and_repos

    except requests.exceptions.RequestException as e:
        return {'error': f'Failed to fetch data from Bitbucket Server: {str(e)}'}


def create_repositories_in_cloud(args, project_data, cloud_url):
    CLOUD_URL = cloud_url
    CLOUD_USERNAME = args['CLOUD_USERNAME']
    CLOUD_PASSWORD = args['CLOUD_PASSWORD']
    WORKSPACE = args['WORKSPACE']

    try:
        for project_info in project_data:
            project_name = project_info['project_name']

            # Create a project in Bitbucket Cloud
            cloud_project_data = {'key': project_name, 'is_private': False, 'name': project_name}
            response_cloud_project = requests.post(f'{CLOUD_URL}/workspaces/{WORKSPACE}/projects',
                                                   auth=(CLOUD_USERNAME, CLOUD_PASSWORD),
                                                   json=cloud_project_data)
            response_cloud_project.raise_for_status()

            # Create repositories in Bitbucket Cloud for each project
            for repo_name in project_info['repositories']:
                cloud_repo_data = {'scm': 'git', 'is_private': False, 'project': {'key': project_name}, 'name': repo_name}
                response_cloud_repo = requests.post(f'{CLOUD_URL}/repositories/{WORKSPACE}/{repo_name}',
                                                   auth=(CLOUD_USERNAME, CLOUD_PASSWORD),
                                                   json=cloud_repo_data)
                response_cloud_repo.raise_for_status()

        return {'message': 'Projects and repositories successfully created in Bitbucket Cloud'}

    except requests.exceptions.RequestException as e:
        return {'error': f'Failed to create projects and repositories in Bitbucket Cloud: {str(e)}'}


def mirror_repositories(args, project_data):
    SERVER_URL = args['SERVER_URL']
    CLOUD_USERNAME = args['CLOUD_USERNAME']
    WORKSPACE = args['WORKSPACE']

    try:
        for project_info in project_data:
            # Clone repositories from Bitbucket Server to a local directory
            for repo_name in project_info['repositories']:
                local_repo_path = f'./{project_info["project_name"]}/{repo_name}'
                if not os.path.exists(local_repo_path):
                    os.makedirs(local_repo_path)
                subprocess.run(['git', 'clone', f'{SERVER_URL}/scm/{project_info["project_name"]}/{repo_name}.git', local_repo_path])

                # Add a remote for the Bitbucket Cloud repository
                subprocess.run(['git', 'remote', 'add', 'cloud', f'https://{CLOUD_USERNAME}@bitbucket.org/{WORKSPACE}/{repo_name}.git'], cwd=local_repo_path)

                # Push to Bitbucket Cloud using the git mirror command
                subprocess.run(['git', 'push', '--mirror', 'cloud'], cwd=local_repo_path)

        return {'message': 'Projects and repositories successfully mirrored to Bitbucket Cloud'}
    except Exception as e:
        return {'error': f'Failed to mirror repositories to Bitbucket Cloud: {str(e)}'}

# Define input parameters for the list_projects endpoint
list_projects_parser = reqparse.RequestParser()
list_projects_parser.add_argument('SERVER_URL', type=str, required=True, help='Bitbucket Server URL')
list_projects_parser.add_argument('SERVER_TOKEN', type=str, required=True, help='Bitbucket Server Token')

# Define input parameters for the create_and_mirror endpoint
create_and_mirror_parser = reqparse.RequestParser()
create_and_mirror_parser.add_argument('SERVER_URL', type=str, required=True, help='Bitbucket Server URL')
create_and_mirror_parser.add_argument('SERVER_TOKEN', type=str, required=True, help='Bitbucket Server Token')
create_and_mirror_parser.add_argument('CLOUD_URL', type=str, required=True, help='Bitbucket Cloud URL')
create_and_mirror_parser.add_argument('CLOUD_USERNAME', type=str, required=True, help='Bitbucket Cloud Username')
create_and_mirror_parser.add_argument('CLOUD_PASSWORD', type=str, required=True, help='Bitbucket Cloud Password')
create_and_mirror_parser.add_argument('WORKSPACE', type=str, required=True, help='Bitbucket Cloud Workspace')
create_and_mirror_parser.add_argument('PROJECT_KEY', type=str, required=False, help='Optional project key')

@ns.route('/list_projects')
class ListProjects(Resource):
    @ns.expect(list_projects_parser)
    @ns.marshal_with(project_fields)
    def get(self):
        args = list_projects_parser.parse_args()
        project_data = list_projects(args)
        if 'error' in project_data:
            return {'error': project_data['error']}, 500
        return project_data

@ns.route('/create_and_mirror')
class CreateAndMirror(Resource):
    @ns.expect(create_and_mirror_parser)
    def post(self):
        args = create_and_mirror_parser.parse_args()
        project_data = list_projects(args)
        if 'error' in project_data:
            return {'error': project_data['error']}, 500
        CLOUD_URL = args['CLOUD_URL']
        create_result = create_repositories_in_cloud(args, project_data, CLOUD_URL)
        if 'error' in create_result:
            return {'error': create_result['error']}, 500

        mirror_result = mirror_repositories(args, project_data)
        if 'error' in mirror_result:
            return {'error': mirror_result['error']}, 500
        return {'message': 'Projects and repositories successfully mirrored to Bitbucket Cloud'}

if __name__ == '__main__':
    app.run(debug=True, port=5000)
