# Automaton (Conway Research, MIT) isolé : ses commandes shell s'exécutent dans ce conteneur, pas sur le PC.
# Code figé au commit vérifié par le cerveau le 03/11/2026 (lockfile et compilation essayés).
FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates curl socat \
    && rm -rf /var/lib/apt/lists/*
ARG COMMIT=d8f816881fd24b6f5e3d616e59edec387a447667
RUN git clone -q https://github.com/Conway-Research/automaton.git /opt/automaton \
    && git -C /opt/automaton checkout -q "$COMMIT"
WORKDIR /opt/automaton
RUN npm install -g pnpm@10.28.1 && pnpm install --frozen-lockfile && pnpm build
# L'agent tourne sans droits root : son code (/opt/automaton) lui reste en lecture seule, il ne peut ni le réécrire
# ni tirer une version plus récente. Ses données vivent dans le volume monté sur ~/.automaton.
RUN mkdir -p /home/node/.automaton && chown node:node /home/node/.automaton
USER node
# Le client d'inférence n'accepte le HTTP simple que vers 127.0.0.1 : socat y relaie l'Ollama du PC.
ENV OLLAMA_BASE_URL=http://127.0.0.1:11434
ENTRYPOINT ["sh", "-c", "socat TCP-LISTEN:11434,bind=127.0.0.1,fork,reuseaddr TCP:host.docker.internal:11434 & exec node /opt/automaton/dist/index.js \"$@\"", "automaton"]
CMD ["--help"]
