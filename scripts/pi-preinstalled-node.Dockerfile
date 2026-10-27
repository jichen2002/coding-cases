ARG BASE_IMAGE=harbor-local/astropy__astropy-7166:1ea65be86880a878
FROM ${BASE_IMAGE}
USER root
RUN mkdir -p /root/.nvm/versions/node/v22.23.4 /root/.nvm/alias
COPY nvm.sh /root/.nvm/nvm.sh
COPY node.tar.xz /tmp/node.tar.xz
RUN tar -xJf /tmp/node.tar.xz --strip-components=1 -C /root/.nvm/versions/node/v22.23.4 \
    && rm /tmp/node.tar.xz \
    && printf 'v22.23.4\n' > /root/.nvm/alias/default \
    && bash -c '. /root/.nvm/nvm.sh && node --version && npm --version'
