FROM apify/actor-python:3.12

COPY requirements.txt ./
RUN echo "Python version:" && python --version \
 && echo "Pip version:" && pip --version \
 && echo "Installing dependencies:" && pip install -r requirements.txt \
 && echo "All installed Python packages:" && pip freeze

COPY . ./

RUN python3 -m compileall -q src/

CMD ["python3", "-m", "src"]
