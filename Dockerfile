#Instruct Podman Engine to use official python:3.14 as the base image
FROM python:3.14

#Create a working directory(app) for the Podman image and container
WORKDIR /code

#Copy the framework and the dependencies of the FastAPI application into the working directory
COPY ./requirements.txt .

#Install the framework and the dependencies in the requirements.txt file in our Podman image and container
RUN pip install -r requirements.txt

#Copy the remaining files and the source code from the host fast-api folder to the FastAPI application container working directory
COPY ./app /code/app

WORKDIR app

#Expose the FastAPI application on port 8080 inside the container
EXPOSE 8080

#Start and run the FastAPI application container
CMD ["uvicorn", "main:app", "--host", "0.0.0.0"]