FROM python:3.8
WORKDIR /app
COPY . /app
RUN pip install -r requirements.txt
ENTRYPOINT [ "python" ]
EXPOSE 5000
CMD [ "app.py" ]