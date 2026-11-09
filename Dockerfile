FROM python:3.13-alpine@sha256:1e1f6334529d1fb26a2ef619d7cffb30a7c7d7cc1cc7338ebee283a58d1aeaca AS snapshot
WORKDIR /src
COPY skills/websummit-planner/assets/websummit.db skills/websummit-planner/assets/websummit.db
COPY skills/websummit-planner/scripts/ skills/websummit-planner/scripts/
RUN python skills/websummit-planner/scripts/export_text.py --out /snapshot

FROM golang:1.27.3-alpine@sha256:fa3d596898d9f126af7c01d14ee7597bab3f39cccf392ef36b69fe77cd681f18 AS build
WORKDIR /src/service
COPY service/go.mod service/go.sum ./
RUN go mod download
COPY service/ ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /server .

FROM scratch
COPY --from=build /server /server
COPY --from=snapshot /snapshot/schedule.json /data/schedule.json
COPY --from=snapshot /snapshot/companies.json /data/companies.json
USER 65532:65532
ENV PORT=8080 SCHEDULE_PATH=/data/schedule.json COMPANIES_PATH=/data/companies.json GOMEMLIMIT=64MiB
EXPOSE 8080
ENTRYPOINT ["/server"]
