#!/bin/bash

set -e

IMAGE_NAME="kklabs/meshbridge"
VERSION=${1:-latest}

echo "========================================="
echo "  Building and Pushing Docker Image"
echo "========================================="
echo "Image: $IMAGE_NAME:$VERSION"
echo ""

echo "[1/4] Setting up buildx builder..."
docker buildx create --use --name meshbridge-builder 2>/dev/null || docker buildx use meshbridge-builder || docker buildx use default

echo "[2/4] Building multi-platform Docker image..."
if [ "$VERSION" != "latest" ]; then
    docker buildx build \
        --platform linux/amd64,linux/arm64 \
        -t $IMAGE_NAME:$VERSION \
        -t $IMAGE_NAME:latest \
        --push \
        .
else
    docker buildx build \
        --platform linux/amd64,linux/arm64 \
        -t $IMAGE_NAME:$VERSION \
        --push \
        .
fi

echo "[3/4] Build and push completed..."

echo ""
echo "========================================="
echo "  ✅ Successfully pushed to Docker Hub"
echo "========================================="
echo "Image: $IMAGE_NAME:$VERSION"
echo ""
echo "To pull and run:"
echo "  docker pull $IMAGE_NAME:$VERSION"
echo "  docker-compose up -d"
