FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends apache2 libapache2-mod-svn subversion openssl ca-certificates \
    && a2enmod ssl dav dav_svn authz_svn \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10003 code-svn && useradd --uid 10003 --gid 10003 --no-create-home code-svn
COPY services/code_svn/apache.conf /opt/code-svn/apache.conf
COPY services/code_svn/manage.py /opt/code-svn/manage.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10003:10003
ENTRYPOINT ["python", "/opt/code-svn/manage.py"]
CMD ["serve"]
