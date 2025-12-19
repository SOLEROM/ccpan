
## test simple gui

xclock &

## test to run opengl app in docker container

```
docker run --rm -it \
  --volume=/tmp/.X11-unix:/tmp/.X11-unix:rw \
  -e DISPLAY=$DISPLAY \
  -e LIBGL_ALWAYS_SOFTWARE=1 \
  ubuntu:22.04 bash -c "apt update && apt install -y mesa-utils && glxgears"

```