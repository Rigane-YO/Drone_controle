import cv2
import pyray as pr


class IntroVideo:
    def __init__(self, path: str) -> None:
        self.video = cv2.VideoCapture(path)

        if not self.video.isOpened():
            raise RuntimeError(
                f"Impossible d'ouvrir la vidéo : {path}"
            )

        self.width = int(
            self.video.get(cv2.CAP_PROP_FRAME_WIDTH)
        )

        self.height = int(
            self.video.get(cv2.CAP_PROP_FRAME_HEIGHT)
        )

        self.fps = self.video.get(cv2.CAP_PROP_FPS)

        if self.fps <= 0:
            self.fps = 30.0

        self.frame_time = 1.0 / self.fps
        self.timer = 0.0

        self.finished = False
        self.texture = None
        self.frame = None

        self._load_first_frame()

    def _load_first_frame(self) -> None:
        success, frame = self.video.read()

        if not success:
            self.finished = True
            return

        self.frame = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGBA
        )

        frame_data = pr.ffi.from_buffer(
            self.frame
        )

        frame_pointer = pr.ffi.cast(
            "void *",
            frame_data
        )

        image = pr.Image(
            frame_pointer,
            self.width,
            self.height,
            1,
            pr.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8
        )

        self.texture = pr.load_texture_from_image(
            image
        )

    def update(self, dt: float) -> None:
        if self.finished:
            return

        self.timer += dt

        if self.timer < self.frame_time:
            return

        self.timer -= self.frame_time

        success, frame = self.video.read()

        if not success:
            self.finished = True
            return

        self.frame = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGBA
        )

        if self.texture is not None:
            frame_data = pr.ffi.from_buffer(
                self.frame
            )

            frame_pointer = pr.ffi.cast(
                "void *",
                frame_data
            )

            pr.update_texture(
                self.texture,
                frame_pointer
            )

    def draw(self) -> None:
        if self.texture is None:
            return

        screen_width = pr.get_screen_width()
        screen_height = pr.get_screen_height()

        video_ratio = self.width / self.height
        screen_ratio = screen_width / screen_height

        if video_ratio > screen_ratio:
            draw_width = screen_width
            draw_height = (
                screen_width / video_ratio
            )
        else:
            draw_height = screen_height
            draw_width = (
                screen_height * video_ratio
            )

        x = (
            screen_width - draw_width
        ) / 2

        y = (
            screen_height - draw_height
        ) / 2

        source = pr.Rectangle(
            0,
            0,
            self.width,
            self.height
        )

        destination = pr.Rectangle(
            x,
            y,
            draw_width,
            draw_height
        )

        origin = pr.Vector2(
            0,
            0
        )

        pr.draw_texture_pro(
            self.texture,
            source,
            destination,
            origin,
            0.0,
            pr.WHITE
        )

    def close(self) -> None:
        if self.texture is not None:
            pr.unload_texture(
                self.texture
            )

            self.texture = None

        self.video.release()