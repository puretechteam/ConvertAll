#version 440
// The 3D viewer's surfaces. Baked to mesh.vert.qsb by packaging/bake_shaders.py.

layout(location = 0) in vec3 position;
layout(location = 1) in vec3 normal;
layout(location = 2) in vec2 uv;
layout(location = 3) in vec4 color;

layout(location = 0) out vec3 v_position;
layout(location = 1) out vec3 v_normal;
layout(location = 2) out vec2 v_uv;
layout(location = 3) out vec4 v_color;

layout(std140, binding = 0) uniform Camera {
    mat4 view_proj;
    vec4 eye;
    vec4 light;
    vec4 sky;
    vec4 ground;
};

void main() {
    v_position = position;
    v_normal = normal;
    v_uv = uv;
    v_color = color;
    gl_Position = view_proj * vec4(position, 1.0);
}
