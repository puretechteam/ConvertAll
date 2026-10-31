#version 440
// Base color x texture x vertex color, lit by a key light near the camera plus a sky/ground
// ambient, with a little Blinn-Phong shine from roughness. Both faces are lit, since many
// models have inconsistent winding. Colors are linear; the output is sRGB-encoded here.

layout(location = 0) in vec3 v_position;
layout(location = 1) in vec3 v_normal;
layout(location = 2) in vec2 v_uv;
layout(location = 3) in vec4 v_color;

layout(location = 0) out vec4 frag_color;

layout(std140, binding = 0) uniform Camera {
    mat4 view_proj;
    vec4 eye;
    vec4 light;
    vec4 sky;
    vec4 ground;
};

layout(std140, binding = 1) uniform Surface {
    vec4 base_color;
    vec4 emissive;
    vec4 params;  // x: has texture, y: alpha cutoff (< 0 = none), z: roughness, w: metallic
};

layout(binding = 2) uniform sampler2D tex;

void main() {
    vec4 base = base_color * v_color;
    if (params.x > 0.5) {
        vec4 t = texture(tex, vec2(v_uv.x, 1.0 - v_uv.y));
        base *= vec4(pow(t.rgb, vec3(2.2)), t.a);
    }
    if (params.y >= 0.0 && base.a < params.y)
        discard;

    vec3 n = normalize(v_normal);
    vec3 view = normalize(eye.xyz - v_position);
    if (dot(n, view) < 0.0)
        n = -n;
    vec3 l = normalize(light.xyz);
    float diffuse = max(dot(n, l), 0.0);
    vec3 ambient = mix(ground.rgb, sky.rgb, n.y * 0.5 + 0.5);
    float rough = clamp(params.z, 0.05, 1.0);
    float shine = pow(max(dot(n, normalize(l + view)), 0.0), mix(96.0, 6.0, rough)) * (1.0 - rough) * 0.35;
    vec3 albedo = base.rgb * (1.0 - 0.6 * params.w);
    vec3 spec = mix(vec3(1.0), base.rgb, params.w) * shine;
    vec3 rgb = albedo * (ambient + diffuse * 0.72) + spec + emissive.rgb;
    frag_color = vec4(pow(clamp(rgb, 0.0, 1.0), vec3(1.0 / 2.2)), base.a);
}
