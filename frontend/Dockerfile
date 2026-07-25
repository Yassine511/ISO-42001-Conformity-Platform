# Base images pinned by digest for reproducible builds; refresh periodically
# (docker pull node:22-alpine / nginx:alpine, then update the digest) for OS
# security fixes — a pinned digest does not receive them automatically.
FROM node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS build
WORKDIR /app
# The digest pin is the point of this image AND its blind spot: `node:22-alpine`
# keeps moving, this reference does not, so a dependency raising its Node floor
# silently outruns the pin. react-router 8 requires Node >= 22.22.0
# (package.json `engines`), and `npm ci` only WARNS on EBADENGINE — the build
# would go on and ship. Fail here instead, naming the fix.
RUN node -e "\
const need = [22, 22, 0], have = process.versions.node.split('.').map(Number); \
const older = have[0] !== need[0] ? have[0] < need[0] \
  : have[1] !== need[1] ? have[1] < need[1] : have[2] < need[2]; \
if (older) { \
  console.error('Node ' + process.versions.node + ' is below the ' + need.join('.') + \
    ' floor declared in frontend/package.json (react-router 8). Refresh the ' + \
    'node:22-alpine digest in frontend/Dockerfile: docker pull node:22-alpine && ' + \
    'docker inspect --format=\"{{index .RepoDigests 0}}\" node:22-alpine'); \
  process.exit(1); \
} \
console.log('node ' + process.versions.node + ' satisfies the ' + need.join('.') + ' floor');"
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine@sha256:54f2a904c251d5a34adf545a72d32515a15e08418dae0266e23be2e18c66fefa
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
