# Project Setup

## Pre-requisites
- Python

## Environment Configuration
Set the following environment variables before running the project:

```sh
export ENV=local
export FLASK_ENV=development
export PYTHONPATH=<>
export SECRET_KEY=<>
export DB_NAME=chat
export DB_PATH=mongodb+srv://<MongoUserName>:<MongoPassword>@chatcluster.xyz.mongodb.net/
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=appointments
export POSTGRES_USERNAME=<>
export POSTGRES_PASSWORD=<>
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

##  Configure MongoDb
Create mongo db with name as "chat". Add collections with following names
```sh
room
message
```

## Configure PostgreSQL
Ensure PostgreSQL database `appointments` exists and includes the required tables:
`service_providers` and `service_slots`.

## Run the app
Run the user service in a separate terminal & run chat service with following command
```sh
python app/run.py
```

