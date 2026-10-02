import pyray as pr

pr.init_window(1000, 700, "Test Drone")

model = pr.load_model("assets/drone.glb")

anim_count = pr.ffi.new("int *")
anims = pr.load_model_animations("assets/drone.glb", anim_count)

print("Nombre animations :", anim_count[0])

for i in range(anim_count[0]):
    print("Animation", i, anims[i])

frame = 0

camera = pr.Camera3D(
    [10, 8, 10],
    [0, 0, 0],
    [0, 1, 0],
    45,
    0
)

while not pr.window_should_close():

    if anim_count[0] > 0:
        pr.update_model_animation(
            model,
            anims[0],
            frame
        )

        frame += 1

        if frame >= anims[0].keyframeCount:
            frame = 0

    pr.begin_drawing()
    pr.clear_background(pr.BLACK)

    pr.begin_mode_3d(camera)

    pr.draw_model(
        model,
        [0, 0, 0],
        1.0,
        pr.WHITE
    )

    pr.draw_grid(20, 1.0)

    pr.end_mode_3d()

    pr.draw_text(
        f"Animations: {anim_count[0]}",
        20, 20, 20, pr.BLACK
    )

    pr.end_drawing()

if anim_count[0] > 0:
    pr.unload_model_animations(anims, anim_count[0])

pr.unload_model(model)
pr.close_window()