FROM amd64/ubuntu:22.04

ENV DEBIAN_FRONTEND noninteractive
ENV LC_ALL C.UTF-8
ENV LANG C.UTF-8

# pre-requisites
RUN apt-get update && apt-get install --no-install-recommends -y --upgrade python3 python3-pip git curl gunicorn coinor-cbc postgresql-client && apt-get clean

WORKDIR /app
# requirements - doing this earlier, so we don't install them each time. Use --no-cache to refresh them.
COPY requirements /app/requirements

# py dev tooling
RUN python3 -m pip install --no-cache-dir --upgrade pip && python3 --version && \
    pip3 install --no-cache-dir --upgrade setuptools && pip3 install highspy && \
    PYV=$(python3 -c "import sys;t='{v[0]}.{v[1]}'.format(v=list(sys.version_info[:2]));sys.stdout.write(t)") && \
    pip3 install --no-cache-dir -r requirements/$PYV/app.txt -r requirements/$PYV/dev.txt -r requirements/$PYV/test.txt

# Copy code and meta/config data
COPY setup.* .flaskenv wsgi.py /app/
COPY flexmeasures/ /app/flexmeasures
RUN find . | grep -E "(__pycache__|\.pyc|\.pyo$)" | xargs rm -rf
COPY .git/ /app/.git

RUN pip3 install --no-cache-dir .

EXPOSE 5000

CMD [ \
    "gunicorn", \
    "--bind", "0.0.0.0:5000", \
    # This is set to /tmp by default, but this is part of the Docker overlay filesystem, and can cause stalls.
    # http://docs.gunicorn.org/en/latest/faq.html#how-do-i-avoid-gunicorn-excessively-blocking-in-os-fchmod
    "--worker-tmp-dir", "/dev/shm", \
    # Ideally you'd want one worker per container, but we don't want to risk the health check timing out because
    # another request is taking a long time to complete.
    "--workers", "2", "--threads", "4", \
    "wsgi:application" \
    ]
