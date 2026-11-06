FROM gcr.io/oss-fuzz-base/base-builder-python

# mdshards' backend is Python 3.14-only (PEP 758 `except A, B:`); the builder
# ships 3.11. Put a 3.14 venv first on PATH so compile_python_fuzzer's bare
# `python3` / `pyinstaller` resolve to it. Kept in lockstep with the repo's
# .clusterfuzzlite/Dockerfile.
ENV UV_PYTHON_INSTALL_DIR=/opt/python
RUN pip3 install --no-cache-dir uv==0.13.7 \
    && uv venv --seed --python 3.14 --managed-python /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir \
        atheris==3.1.0 pyinstaller==6.22.3 coverage==7.17.1
ENV PATH=/opt/venv/bin:$PATH

RUN git clone --depth 1 https://github.com/wzaldivar/mdshards mdshards
WORKDIR mdshards
COPY build.sh $SRC/
