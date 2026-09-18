GO      ?= go
BINARY  ?= gateway
PKG     ?= ./...

.PHONY: all build run test test-race vet fmt tidy lint cover docker clean

all: fmt vet test build

## build: compile the gateway binary into ./bin
build:
	$(GO) build -o bin/$(BINARY) ./cmd/gateway

## run: run the gateway with development defaults
run:
	$(GO) run ./cmd/gateway

## test: run the full test suite
test:
	$(GO) test $(PKG)

## test-race: run tests with the race detector
test-race:
	$(GO) test -race $(PKG)

## cover: run tests and print coverage
cover:
	$(GO) test -coverprofile=coverage.out $(PKG)
	$(GO) tool cover -func=coverage.out | tail -1

## vet: run go vet
vet:
	$(GO) vet $(PKG)

## fmt: format all Go source
fmt:
	$(GO) fmt $(PKG)

## tidy: tidy the module graph
tidy:
	$(GO) mod tidy

## docker: build the container image
docker:
	docker build -t obol/obol-gateway:dev .

## clean: remove build artifacts
clean:
	rm -rf bin coverage.out
