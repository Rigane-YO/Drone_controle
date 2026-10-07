import pyray as pr

from intro_video import IntroVideo


WIDTH = 1200
HEIGHT = 800


pr.init_window(WIDTH, HEIGHT, "Fly-in - Intro")
pr.set_target_fps(60)

intro = IntroVideo("assets/intro.mp4")


while not pr.window_should_close() and not intro.finished:
    dt = pr.get_frame_time()

    intro.update(dt)

    pr.begin_drawing()

    pr.clear_background(pr.BLACK)

    intro.draw(WIDTH, HEIGHT)

    pr.end_drawing()


intro.close()

pr.close_window()