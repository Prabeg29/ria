## Prerequisites
- Docker

1. Clone the repository
```sh
$ git clone git@github.com:Prabeg29/ria.git
$ cd ria
$ cp .env.example .env
```

2. Build docker image for dev stage
```sh
$ docker compose -f dev.docker-compose.yml build base --no-cache
```