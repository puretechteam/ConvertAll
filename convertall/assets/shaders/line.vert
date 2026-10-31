#version 440
// The viewer's wireframe and ground grid. Baked to line.vert.qsb by packaging/bake_shaders.py.

layout(location = 0) in vec3 position;

layout(std140, binding = 0) uniform Camera {
    mat4 view_proj;
    vec4 eye;
    vec4 light;
    vec4 sky;
    vec4 ground;
};

void main() {
    gl_Position = view_proj * vec4(position, 1.0);
}
