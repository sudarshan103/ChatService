# Project Setup

## Pre-requisites
- Python
- Redis

## Environment Configuration
Set the following environment variables before running the project:

```sh
export ENV=local
export FLASK_ENV=development
export PYTHONPATH=<>
export SECRET_KEY=<>
export DB_NAME=chat
export DB_PATH=mongodb+srv://<MongoUserName>:<MongoPassword>@chatcluster.xyz.mongodb.net/
```

Replace placeholders (`<>`) with the appropriate values.

Make sure these are loaded in your current terminal context, by technique like:
```sh
source env_config/local.env
```

## Install dependencies
Ensure that you activate virtual environment & install app dependencies
```sh
pip install -r requirement.txt
```

## Run the app
Run the user service in a separate terminal & run chat service with following command
```sh
python app/run.py
```

##  Create the mongo data
Create mongo db with name as "chat". Add collections with following names
```sh
room
message
```