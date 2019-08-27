
FROM python:2.7

ENV REDIS_SENTINEL=redis-sentinel
ENV REDIS_MASTER=redis-master

# install git and various python library dependencies with alpine tools
RUN set -x && \
    apt-get update && \
    apt-get install -y postgresql postgresql-server-dev-all libpq-dev python-psycopg2 \
                       libsasl2-dev libldap2-dev libssl-dev python-dev build-essential \
                       libjpeg-dev libssl-dev libffi-dev dbus libdbus-1-dev libdbus-glib-1-dev \
                       libldap2-dev libsasl2-dev

# install python dependencies with pip
# install pybossa from git
# add unprivileged user for running the service
ENV LIBRARY_PATH=/lib:/usr/lib
ADD . /opt/pybossa
WORKDIR /opt/pybossa
RUN set -x && \
    cd /opt/pybossa && \
    pip install -U pip setuptools && \
    pip install -r /opt/pybossa/requirements.txt && \
    pip install minio && \
    pip install pdfminer && \
    pip install wget && \
    rm -rf /opt/pybossa/.git/

# variables in these files are modified with sed from /entrypoint.sh
ADD alembic.ini /opt/pybossa/
ADD settings_local.py /opt/pybossa/

ADD entrypoint.sh /
RUN ["chmod", "+x", "/entrypoint.sh"]
ENTRYPOINT ["sh", "/entrypoint.sh"]

EXPOSE 5000
