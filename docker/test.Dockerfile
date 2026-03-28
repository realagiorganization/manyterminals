FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends tmux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work/manyterminals

COPY requirements-test.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-test.txt

COPY . .

CMD ["pytest", "-q"]
