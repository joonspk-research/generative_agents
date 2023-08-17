FROM python:3.10


WORKDIR /app

COPY docker/entrypoint.sh /entrypoint.sh
COPY requirements.txt requirements.txt
COPY reverie reverie

RUN pip install -r requirements.txt

ENTRYPOINT ["/entrypoint.sh"]
