# PYTHON ENVIRMENT CREATE
import subprocess
import sys
import os


from templete import gitignore,readme,requirement
class WorkspacePython:
    def __init__(self,folder):
        self.folder_path = folder
        os.makedirs(self.folder_path, exist_ok = True )

    def setup(self):
        print('Creating virtual enviroment in ',self.folder_path)
        self.venv()

        print('Setup README, Requirment and gitignore file ..... ')
        self.need_file_create()

        print('Folder setup ....')
        self.folder_setup()

        print('Git initilization .... ')
        self.init_git_repo()

        print('Workspace complete. All file and folder succesfully created ! ')


    def venv(self):
        '''This create virtual enviroment'''
        venv_path = os.path.abspath(os.path.join(self.folder_path,'venv'))
        command_venv = [sys.executable,'-m','venv',venv_path]

        try:
            if not os.path.exists(venv_path):
                result = subprocess.run(
                    command_venv,
                    capture_output=True,
                    text=True
                )

                print('Virtual enviroment create successfully!')
                print(f"Activate it using:\nsource venv/bin/activate")

            else:
                print('Already venv file exist')


        except subprocess.CalledProcessError as e:
            print(f"Failed to create virtual environment.\nError:\n{e.stderr}")

    def need_file_create(self):
        #create requirement.txt
        
        file_list = ['requirement.txt','README.md','.gitignore']

        for i in file_list:
            path = os.path.join(self.folder_path,i)
            with open(path,'w') as f:
                if i == 'requirement.txt':
                    f.write(requirement)

                elif i == '.gitignore':
                    f.write(gitignore)

                elif i == 'README.md':
                    f.write(readme)

    def folder_setup(self):
        folder_name = ['src','test','bin']

        for i in folder_name:
            path = os.path.join(self.folder_path,i)

            os.makedirs(path,exist_ok=True)

            if i == 'src':
                with open(os.path.join(path,'main.py'),'w') as f:
                    f.write('# write your code here')

                with open(os.path.join(path,'code.ipynb'),'w') as f:
                                    f.write('# write your code here')

            elif i == 'test':
                with open(os.path.join(path,'test.py'),'w') as f:
                    f.write('# write your test code here')


    def init_git_repo(self):
        # 1. Expand user shortcuts (like ~) and resolve relative paths
        self.folder_path = os.path.abspath(os.path.expanduser(self.folder_path))

        # 2. Create the target directory if it doesn't already exist
        os.makedirs(self.folder_path, exist_ok=True)

        # 3. Check if .git folder already exists
        git_dir = os.path.join(self.folder_path, ".git")
        if os.path.exists(git_dir):
            print(f"⚠️ Git repository already initialized at: {self.folder_path}")
            return

        # 4. Run `git init` inside the specific folder
        try:
            # Option A: Pass the target directory path directly to git init
            result = subprocess.run(
                ["git", "init", self.folder_path],
                check=True,
                capture_output=True,
                text=True,
            )

            print(f"✅ Successfully initialized Git repository at: {self.folder_path}")

            choice = (
                input("Which workspace do you want to choose [personal/work]: ")
                .strip()
                .lower()
            )

            # 3. Define account mappings
            if choice == "personal":
                email = "satorugojo0087@gmail.com"
                name = "Personal Account"  # Change to your preferred display name
            elif choice == "work":
                email = "imleo0087@gmail.com"
                name = "Darshan Chaulagain"  # Your work display name
            else:
                print("⚠️ Invalid choice! Defaulting to work account.")
                email = "imleo0087@gmail.com"
                name = "Darshan Chaulagain"

            # 4. Set local git user.email
            subprocess.run(
                ["git", "config", "user.email", email],
                cwd=self.folder_path,
                check=True,
            )

            # 5. Set local git user.name
            subprocess.run(
                ["git", "config", "user.name", name],
                cwd=self.folder_path,
                check=True,
            )

            print(f"👤 Set Git identity for this repo to: {name} <{email}>")

        except subprocess.CalledProcessError as e:
            print(
                f"❌ Failed to initialize Git repository.\nError: {e.stderr.strip()}"
            )
        except FileNotFoundError:
            print(
                "❌ Git is not installed on your system. Run 'sudo apt install git' on Ubuntu."
            )

if __name__ == '__main__':
    work = WorkspacePython('/home/leo/newproject')

    work.setup()
