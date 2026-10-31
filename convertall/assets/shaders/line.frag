#version 440

layout(location = 0) out vec4 frag_color;

layout(std140, binding = 1) uniform Line {
    vec4 color;
};

void main() {
    frag_color = color;
}
