# syntax=docker/dockerfile:1
# Thin enabling-point: weighted reverse proxy fronting legacy vs canary.
# CANARY_PCT is data (env), flipped only behind a passed deploy gate.
FROM nginx:1.27-alpine
COPY router.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 8080
