#!/usr/bin/bash

#DISABLED_LOGGING_FLAGS="--log-disable=matplotlib --log-disable=matplotlib.pyplot --log-disable=matplotlib.colorbar --log-disable=matplotlib.font_manager --log-disable=numexpr.utils --log-disable=sentence_transformers.SentenceTransformer --log-disable=urllib3.connectionpool"
DISABLED_LOGGING_FLAGS=""

set -x
pytest ${DISABLED_LOGGING_FLAGS} --log-cli-level=DEBUG $@
set +x
