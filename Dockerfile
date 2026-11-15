# LakePulse web page: static files served by nginx as a non-root user on port 8080
# (Cloud Run's default). Only web/ is served: it is copied into a fresh folder that nginx
# uses as its root, so nginx's own sample files (e.g. 50x.html) are never reachable.
FROM nginxinc/nginx-unprivileged:1.27.4-alpine

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/security-headers.conf /etc/nginx/conf.d/security-headers.inc
COPY web/ /srv/lakepulse/

EXPOSE 8080
