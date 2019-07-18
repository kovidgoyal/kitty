/*
 * glfw_tests.c
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "glfw_tests.h"


#include "glfw-wrapper.h"
#include "gl.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static volatile bool running = true;

static void* empty_thread_main(void* data UNUSED)
{
    struct timespec time = { .tv_sec = 1 };

    while (running)
    {
        nanosleep(&time, NULL);
        wakeup_main_loop();
    }

    return 0;
}

static void key_callback(GLFWwindow *w UNUSED, int key, int scancode UNUSED, int action, int mods UNUSED, const char* text UNUSED, int state UNUSED)
{
    if (key == GLFW_KEY_ESCAPE && action == GLFW_PRESS) {
        glfwSetWindowShouldClose(w, true);
        wakeup_main_loop();
    }
}

static void
window_close_callback(GLFWwindow* window) {
    glfwSetWindowShouldClose(window, true);
    wakeup_main_loop();
}


static float nrand(void)
{
    return (float) rand() / (float) RAND_MAX;
}

static void
empty_main_tick(void *data) {
    GLFWwindow *window = data;
    if (glfwWindowShouldClose(window)) {
        running = false;
        glfwStopMainLoop();
        return;
    }
    int width, height;
    float r = nrand(), g = nrand(), b = nrand();
    float l = (float) sqrt(r * r + g * g + b * b);

    glfwGetFramebufferSize(window, &width, &height);

    glViewport(0, 0, width, height);
    glClearColor(r / l, g / l, b / l, 1.f);
    glClear(GL_COLOR_BUFFER_BIT);
    glfwSwapBuffers(window);
}

int empty_main(void)
{
    pthread_t thread;
    GLFWwindow* window;
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, OPENGL_REQUIRED_VERSION_MAJOR);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, OPENGL_REQUIRED_VERSION_MINOR);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
    glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, true);


    srand((unsigned int) time(NULL));

    window = glfwCreateWindow(640, 480, "Empty Event Test", NULL, NULL);
    if (!window)
    {
        return (EXIT_FAILURE);
    }

    glfwMakeContextCurrent(window);
    gl_init();
    glfwSetKeyboardCallback(window, key_callback);
    glfwSetWindowCloseCallback(window, window_close_callback);

    if (pthread_create(&thread, NULL, empty_thread_main, NULL) != 0)
    {
        fprintf(stderr, "Failed to create secondary thread\n");
        return (EXIT_FAILURE);
    }

    glfwRunMainLoop(empty_main_tick, window);

    glfwHideWindow(window);
    pthread_join(thread, NULL);
    glfwDestroyWindow(window);

    return (EXIT_SUCCESS);
}
