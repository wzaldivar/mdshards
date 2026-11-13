FROM gcr.io/oss-fuzz-base/base-builder-python

# The OSS-Fuzz builder ships Python 3.11, but the backend is 3.14-only (PEP
# 758 `except A, B:`), so it won't even parse there. Put a 3.14 venv first on
# PATH: compile_python_fuzzer calls bare `python3` / `pyinstaller`, so both
# resolve to it. Atheris has cp314 wheels; coverage must be new enough for
# 3.14 (the builder's pinned 6.3.2 isn't).
ENV UV_PYTHON_INSTALL_DIR=/opt/python
RUN pip3 install --no-cache-dir uv==0.13.7 \
    && uv venv --seed --python 3.14 --managed-python /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir \
        atheris==3.1.0 pyinstaller==6.22.3 coverage==7.17.1
ENV PATH=/opt/venv/bin:$PATH

COPY . $SRC/mdshards
WORKDIR $SRC/mdshards
COPY .clusterfuzzlite/build.sh $SRC/
