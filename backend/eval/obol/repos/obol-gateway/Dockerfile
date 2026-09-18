# --- build stage ---
FROM golang:1.22-alpine AS build

WORKDIR /src

# Cache module downloads. There are no third-party deps, but this keeps the
# layer stable if any are added later.
COPY go.mod ./
RUN go mod download

COPY . .

# Build a static binary.
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /out/gateway ./cmd/gateway

# --- runtime stage ---
FROM gcr.io/distroless/static-debian12:nonroot

WORKDIR /
COPY --from=build /out/gateway /gateway

# Public API port.
EXPOSE 8080

# Sensible defaults; override at runtime.
ENV GATEWAY_ADDR=":8080" \
    GATEWAY_ENV="production"

USER nonroot:nonroot
ENTRYPOINT ["/gateway"]
