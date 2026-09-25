"""
Builds the two cars for Launch in Blender and exports them as .glb files.

Run with Blender's Python (the `bpy` module):
    python3 launch/src/build_cars.py            # writes launch/roadster.glb and launch/911.glb
    python3 launch/src/build_cars.py --preview  # also renders side/front/top/3-4 checks

Every body is a loft: a run of cross-sections down the car's length, each one a
smooth curve through eight control points whose positions are keyframed along
the car. Wheel arches are cut with booleans, then wheels, brakes, mirrors and
the 911's wing are modelled as separate parts. Paint, glass, lamps and trim are
not split into separate meshes: the page draws them onto the body in a shader,
so their edges stay crisp at any distance.

Blender axes: +X is forward, +Y is the car's left, +Z is up, and the origin
sits on the ground halfway between the axles.
"""
import sys, os, math
import numpy as np
import bpy, bmesh
from mathutils import Vector, Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.dirname(HERE)

# ---------------------------------------------------------------- helpers

def pchip(xs, ys, x):
    """Monotone cubic interpolation, so keyframed profiles never overshoot."""
    xs = np.asarray(xs, float); ys = np.asarray(ys, float)
    order = np.argsort(xs); xs = xs[order]; ys = ys[order]
    x = np.clip(np.asarray(x, float), xs[0], xs[-1])
    h = np.diff(xs); d = np.diff(ys) / h
    n = len(xs); m = np.zeros(n)
    if n == 2:
        m[:] = d[0]
    else:
        for k in range(1, n - 1):
            if d[k - 1] * d[k] <= 0: m[k] = 0
            else:
                w1 = 2 * h[k] + h[k - 1]; w2 = h[k] + 2 * h[k - 1]
                m[k] = (w1 + w2) / (w1 / d[k - 1] + w2 / d[k])
        m[0] = d[0]; m[-1] = d[-1]
    i = np.clip(np.searchsorted(xs, x) - 1, 0, n - 2)
    t = (x - xs[i]) / h[i]
    t2 = t * t; t3 = t2 * t
    return ((2*t3 - 3*t2 + 1) * ys[i] + (t3 - 2*t2 + t) * h[i] * m[i]
            + (-2*t3 + 3*t2) * ys[i + 1] + (t3 - t2) * h[i] * m[i + 1])


def catmull(points, per_seg):
    """Centripetal Catmull-Rom through an open list of 2-D points."""
    P = np.asarray(points, float)
    # phantom end points mirrored across the centreline (y = 0), so the curve
    # meets its mirror image flat instead of leaving a ridge down the car
    ext = np.vstack([P[1] * [-1, 1], P, P[-2] * [-1, 1]])
    out = []
    for s in range(len(P) - 1):
        p0, p1, p2, p3 = ext[s], ext[s + 1], ext[s + 2], ext[s + 3]
        def tj(ti, a, b): return ti + max(np.linalg.norm(b - a), 1e-6) ** 0.5
        t0 = 0; t1 = tj(t0, p0, p1); t2 = tj(t1, p1, p2); t3 = tj(t2, p2, p3)
        n = per_seg[s] if hasattr(per_seg, '__len__') else per_seg
        for k in range(n):
            t = t1 + (t2 - t1) * k / n
            a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
            a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
            a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
            b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
            b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
            out.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    out.append(P[-1])
    return np.array(out)


def material(name, color, metal=0.0, rough=0.5, emit=None):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Metallic"].default_value = metal
    b.inputs["Roughness"].default_value = rough
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = 4.0
    return m


def mesh_obj(name, verts, faces, mat=None, smooth=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    me.validate(); me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    if mat: ob.data.materials.append(mat)
    if smooth:
        for p in me.polygons: p.use_smooth = True
    return ob


def apply_mods(ob):
    bpy.context.view_layer.objects.active = ob
    for o in bpy.context.selected_objects: o.select_set(False)
    ob.select_set(True)
    for m in list(ob.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)


def revolve(profile, segs, mat, name, axis='Y'):
    """Spin an (r, y) profile round the Y axis. Profile runs open, from inside out."""
    verts = []; faces = []
    n = len(profile)
    for s in range(segs):
        a = 2 * math.pi * s / segs
        ca, sa = math.cos(a), math.sin(a)
        for r, y in profile:
            verts.append((r * ca, y, r * sa))
    for s in range(segs):
        s2 = (s + 1) % segs
        for k in range(n - 1):
            faces.append((s * n + k, s * n + k + 1, s2 * n + k + 1, s2 * n + k))
    return mesh_obj(name, verts, faces, mat)


def box_between(bm, p_in, p_out, w_in, w_out, t_in, t_out, twist=0.0):
    """A tapered bar from hub to rim in the wheel plane (XZ), thickness along Y."""
    p_in = Vector(p_in); p_out = Vector(p_out)
    d = (p_out - p_in).normalized()
    side = Vector((-d.z, 0, d.x))
    vs = []
    for p, w, t, tw in ((p_in, w_in, t_in, 0), (p_out, w_out, t_out, twist)):
        for sy, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            off = side * (w / 2 * sy) + Vector((0, t / 2 * sz, 0))
            off = off + side * (tw * sz)
            vs.append(bm.verts.new(p + off))
    f = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    for q in f: bm.faces.new([vs[i] for i in q])

# ---------------------------------------------------------------- the loft

def build_body(spec, mats):
    L = spec['keys']
    def k(name, x): return pchip([a for a, _ in L[name]], [b for _, b in L[name]], x)
    x0, x1 = spec['rear'], spec['front']
    NS = 260
    # cosine spacing crowds sections toward nose and tail where the curvature is
    u = np.linspace(0, 1, NS)
    xs = x0 + (x1 - x0) * (0.5 - 0.5 * np.cos(np.pi * u)) * 0.6 + (x1 - x0) * u * 0.4
    per = [7, 10, 10, 10, 10, 12, 14]  # samples per span between the 8 control points
    rf, rr = spec['round_front'], spec['round_rear']
    rings = []
    for x in xs:
        P = [
            (0.0,            k('zb', x)),
            (k('wl', x),     k('zb', x)),
            (k('w', x),      k('zs', x)),
            (k('w', x),      k('zm', x)),
            (k('wb', x),     k('zbelt', x)),
            (k('wg', x),     k('zg', x)),
            (k('wr', x),     k('zr', x)),
            (0.0,            k('zc', x)),
        ]
        ring = catmull(P, per)
        ring[:, 0] = np.maximum(ring[:, 0], 0)
        ring[0, 0] = 0; ring[-1, 0] = 0
        # round the nose and tail off in plan and in elevation
        for (xa, xb, kz, zn) in ((x1 - rf[0], x1, rf[1], rf[2]), (x0 + rr[0], x0, rr[1], rr[2])):
            t = (x - xa) / (xb - xa)
            if 0 < t <= 1:
                e = math.sqrt(max(0.0, 1 - t ** 2.2))
                ring[:, 0] *= e ** 0.8
                # squeeze the section toward the bumper's leading height, so the
                # end reads as a rounded wedge from the side, not a wall
                ring[:, 1] = zn + (ring[:, 1] - zn) * (1 - kz * (1 - e))
        rings.append(ring)
    M = len(rings[0])
    verts = []; faces = []
    for i, (x, ring) in enumerate(zip(xs, rings)):
        for y, z in ring: verts.append((x, y, z))
    for i in range(NS - 1):
        for j in range(M - 1):
            a = i * M + j; b = (i + 1) * M + j
            faces.append((a, b, b + 1, a + 1))
    ob = mesh_obj('body', verts, faces, mats['paint'])
    # remove the zero-area quads the closed ends leave behind, then mirror
    bpy.context.view_layer.objects.active = ob
    bm = bmesh.new(); bm.from_mesh(ob.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-5)
    bm.to_mesh(ob.data); bm.free()
    mir = ob.modifiers.new('mirror', 'MIRROR')
    mir.use_axis[0] = False; mir.use_axis[1] = True
    mir.use_clip = True; mir.use_mirror_merge = True; mir.merge_threshold = 1e-4
    apply_mods(ob)
    bm = bmesh.new(); bm.from_mesh(ob.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(ob.data); bm.free()

    # wheel arches: all four cutters joined and cut in one exact boolean
    cutters = []
    for (xa, R, yin) in spec['arches']:
        for side in (1, -1):
            depth = 1.4
            bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=R, depth=depth,
                location=(xa, side * (yin + depth / 2), spec['arch_z'](R)),
                rotation=(math.pi / 2, 0, 0))
            cutters.append(bpy.context.active_object)
    if cutters:
        for o in bpy.context.selected_objects: o.select_set(False)
        for c in cutters: c.select_set(True)
        bpy.context.view_layer.objects.active = cutters[0]
        bpy.ops.object.join()
        cut = bpy.context.active_object
        cut.data.materials.append(mats['well'])
        m = ob.modifiers.new('arch', 'BOOLEAN')
        m.operation = 'DIFFERENCE'; m.solver = 'EXACT'; m.object = cut
        m.material_mode = 'TRANSFER'
        apply_mods(ob)
        bpy.data.objects.remove(cut, do_unlink=True)
    ws = ob.modifiers.new('wn', 'WEIGHTED_NORMAL'); ws.keep_sharp = True
    ob.data.set_sharp_from_angle(angle=math.radians(40))
    apply_mods(ob)
    return ob

# ---------------------------------------------------------------- wheels

def build_wheel(name, R, W, Rrim, style, mats, side, loc):
    parts = []
    # tyre: tread, rounded shoulders, sidewall with a little bulge
    hw = W / 2
    prof = [
        (Rrim + 0.004, -hw + 0.012), (Rrim + 0.03, -hw - 0.004), (R - 0.05, -hw - 0.010),
        (R - 0.018, -hw + 0.004), (R - 0.004, -hw + 0.022), (R, -hw + 0.04),
        (R, hw - 0.04), (R - 0.004, hw - 0.022), (R - 0.018, hw - 0.004),
        (R - 0.05, hw + 0.010), (Rrim + 0.03, hw + 0.004), (Rrim + 0.004, hw - 0.012),
    ]
    parts.append(revolve(prof, 96, mats['tire'], name + '_tire'))
    # rim barrel and outer lip
    rim = [
        (Rrim - 0.03, -hw + 0.02), (Rrim - 0.005, -hw + 0.015), (Rrim - 0.005, hw - 0.012),
        (Rrim + 0.012, hw - 0.004), (Rrim + 0.012, hw + 0.004), (Rrim - 0.012, hw + 0.006),
        (Rrim - 0.022, hw - 0.004),
    ]
    parts.append(revolve(rim, 96, mats['rim'], name + '_barrel'))
    # dark inner dish so the gaps between spokes read as depth, not sky
    dish = [(0.07, hw - 0.12), (Rrim - 0.02, hw - 0.075)]
    parts.append(revolve(dish, 64, mats['rim_dark'], name + '_dish'))
    # brake disc (drilled look comes from the shader-less dark tone)
    disc = [(0.09, -0.017 + hw - 0.13), (Rrim - 0.055, -0.017 + hw - 0.13),
            (Rrim - 0.055, 0.017 + hw - 0.13), (0.09, 0.017 + hw - 0.13)]
    parts.append(revolve(disc, 64, mats['disc'], name + '_disc'))
    # spokes
    bm = bmesh.new()
    face_y = hw - 0.012
    if style == 'porsche':
        n = 5
        for s in range(n):
            base = 2 * math.pi * s / n
            for off in (-0.13, 0.13):
                a_in = base + off * 0.35; a_out = base + off
                p_in = (0.075 * math.cos(a_in), face_y - 0.055, 0.075 * math.sin(a_in))
                p_out = ((Rrim - 0.015) * math.cos(a_out), face_y - 0.004, (Rrim - 0.015) * math.sin(a_out))
                box_between(bm, p_in, p_out, 0.040, 0.030, 0.034, 0.022)
    else:  # roadster: a turbine of slim blades
        n = 14
        for s in range(n):
            a_in = 2 * math.pi * s / n; a_out = a_in + 0.28
            p_in = (0.07 * math.cos(a_in), face_y - 0.045, 0.07 * math.sin(a_in))
            p_out = ((Rrim - 0.012) * math.cos(a_out), face_y - 0.004, (Rrim - 0.012) * math.sin(a_out))
            box_between(bm, p_in, p_out, 0.024, 0.032, 0.03, 0.018, twist=0.004)
    me = bpy.data.meshes.new(name + '_spokes'); bm.to_mesh(me); bm.free()
    sp = bpy.data.objects.new(name + '_spokes', me); bpy.context.collection.objects.link(sp)
    sp.data.materials.append(mats['rim'])
    bv = sp.modifiers.new('bevel', 'BEVEL'); bv.width = 0.004; bv.segments = 2
    wn = sp.modifiers.new('wn', 'WEIGHTED_NORMAL')
    apply_mods(sp)
    parts.append(sp)
    # hub / centre lock
    hub = [(0.0, face_y - 0.02), (0.045, face_y - 0.022), (0.06, face_y - 0.04),
           (0.085, face_y - 0.06)]
    parts.append(revolve(hub, 48, mats['rim'] if style == 'roadster' else mats['nut'], name + '_hub'))
    # join, mirror for the right-hand side, place
    for o in bpy.context.selected_objects: o.select_set(False)
    for p in parts: p.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    wheel = bpy.context.active_object
    wheel.name = name
    if side < 0:
        wheel.data.transform(Matrix.Scale(-1, 4, (0, 1, 0)))
        wheel.data.flip_normals()
    wheel.location = loc
    return wheel


def build_caliper(name, Rrim, W, side, loc, mat):
    # a curved block hugging the disc, just behind the axle's top
    hw = W / 2
    bm = bmesh.new()
    segs = 8; a0, a1 = math.radians(95), math.radians(150)
    r_in, r_out = Rrim - 0.12, Rrim - 0.035
    y_in, y_out = hw - 0.17, hw - 0.09
    ring = []
    for s in range(segs + 1):
        a = a0 + (a1 - a0) * s / segs
        c, sn = math.cos(a), math.sin(a)
        ring.append([bm.verts.new((r * c, y, r * sn)) for r, y in
                     ((r_in, y_in), (r_out, y_in), (r_out, y_out), (r_in, y_out))])
    for s in range(segs):
        for q in range(4):
            q2 = (q + 1) % 4
            bm.faces.new((ring[s][q], ring[s][q2], ring[s + 1][q2], ring[s + 1][q]))
    bm.faces.new(ring[0][::-1]); bm.faces.new(ring[-1])
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(ob)
    ob.data.materials.append(mat)
    bv = ob.modifiers.new('bevel', 'BEVEL'); bv.width = 0.006; bv.segments = 2
    apply_mods(ob)
    for p in ob.data.polygons: p.use_smooth = True
    if side < 0:
        ob.data.transform(Matrix.Scale(-1, 4, (0, 1, 0))); ob.data.flip_normals()
    ob.location = loc
    return ob

# ---------------------------------------------------------------- small parts

def build_mirror(name, loc, size, mat, root, trim):
    """Door mirror: a teardrop housing on a short arm that meets the door at `root`."""
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1, location=(0, 0, 0))
    ob = bpy.context.active_object; ob.name = name
    ob.scale = size
    bpy.ops.object.transform_apply(scale=True)
    for v in ob.data.vertices:
        # flat mirror face at the back, a longer nose at the front
        if v.co.x < -size[0] * 0.3: v.co.x = -size[0] * 0.3
        if v.co.x > 0: v.co.x *= 1.35
    ob.data.materials.append(mat)
    for p in ob.data.polygons: p.use_smooth = True
    ob.location = loc
    # the arm
    a = Vector(root); b = Vector(loc) + Vector((0.02, -0.03 * (1 if loc[1] > 0 else -1), -0.02))
    d = b - a
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.016, depth=d.length, location=(a + b) / 2)
    arm = bpy.context.active_object
    arm.rotation_euler = d.to_track_quat('Z', 'Y').to_euler()
    arm.scale = (1.6, 0.7, 1)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    arm.data.materials.append(trim)
    for p in arm.data.polygons: p.use_smooth = True
    for o in bpy.context.selected_objects: o.select_set(False)
    ob.select_set(True); arm.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.join()
    return ob


def build_lens(body, name, y, z, radii, mat):
    """A domed headlamp lens seated on the body where a ray from the front lands."""
    ok, loc, nrm, _ = body.ray_cast(Vector((5, y, z)), Vector((-1, 0, 0)))
    if not ok: return None
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1)
    ob = bpy.context.active_object; ob.name = name
    ob.scale = radii  # x is the depth along the surface normal
    bpy.ops.object.transform_apply(scale=True)
    ob.rotation_euler = nrm.to_track_quat('X', 'Z').to_euler()
    ob.location = loc - nrm * (radii[0] * 0.45)
    bpy.ops.object.transform_apply(location=True, rotation=True)
    for p in ob.data.polygons: p.use_smooth = True
    ob.data.materials.append(mat)
    return ob


def build_wing(spec, mats):
    # a thin airfoil across the tail; the page raises it with speed
    span = spec['span']; c = spec['chord']
    foil = [(0, 0), (0.25, 0.018), (0.6, 0.02), (1.0, 0.004), (0.6, -0.004), (0.25, -0.006)]
    verts = []; faces = []
    N = 40
    for i in range(N + 1):
        y = -span / 2 + span * i / N
        t = abs(y) / (span / 2)
        droop = 0.012 * t ** 4
        for fx, fz in foil:
            verts.append((-fx * c, y, fz * c * 1.6 - droop))
    n = len(foil)
    for i in range(N):
        for j in range(n):
            a = i * n + j; b = i * n + (j + 1) % n
            faces.append((a, b, b + n, a + n))
    faces.append(tuple(range(n))[::-1])
    faces.append(tuple(N * n + j for j in range(n)))
    ob = mesh_obj('wing', verts, faces, mats['trim'])
    return ob

# ---------------------------------------------------------------- the cars

def arch_z(R): return R


PORSCHE = dict(
    name='911', rear=-2.29, front=2.245, round_front=(0.32, 0.55, 0.40), round_rear=(0.15, 0.4, 0.62),
    wheelbase=2.45, track_f=1.59, track_r=1.55,
    wheel_f=(0.343, 0.255, 0.254), wheel_r=(0.362, 0.315, 0.267),
    rim='porsche',
    keys=dict(
        zb=[(-2.29, 0.38), (-2.2, 0.30), (-2.0, 0.22), (-1.6, 0.17), (0, 0.14), (1.6, 0.15), (2.0, 0.16), (2.16, 0.18), (2.245, 0.28)],
        wl=[(-2.29, 0.72), (-1.2, 0.80), (0, 0.76), (1.2, 0.76), (2.245, 0.66)],
        w=[(-2.29, 0.87), (-2.0, 0.93), (-1.3, 0.955), (-0.7, 0.905), (0.0, 0.885), (0.8, 0.895), (1.25, 0.925), (1.8, 0.905), (2.1, 0.86), (2.245, 0.80)],
        zs=[(-2.29, 0.45), (-1.9, 0.33), (-1.5, 0.26), (0, 0.22), (1.6, 0.24), (2.1, 0.25), (2.245, 0.32)],
        zm=[(-2.29, 0.62), (-1.3, 0.60), (0, 0.52), (1.2, 0.52), (2.245, 0.36)],
        wb=[(-2.29, 0.84), (-2.0, 0.90), (-1.25, 0.925), (-0.6, 0.84), (0.2, 0.83), (0.9, 0.85), (1.3, 0.87), (1.9, 0.82), (2.245, 0.68)],
        zbelt=[(-2.29, 0.84), (-2.0, 0.88), (-1.3, 0.88), (-0.7, 0.87), (0.1, 0.845), (0.7, 0.80), (1.0, 0.775), (1.25, 0.77), (1.6, 0.745), (1.9, 0.70), (2.1, 0.63), (2.245, 0.44)],
        wg=[(-2.29, 0.72), (-2.0, 0.80), (-1.5, 0.78), (-1.0, 0.70), (-0.4, 0.71), (0.3, 0.72), (0.7, 0.74), (1.2, 0.73), (1.8, 0.71), (2.1, 0.66), (2.245, 0.56)],
        zg=[(-2.29, 0.87), (-2.0, 0.94), (-1.5, 0.97), (-1.0, 0.95), (-0.4, 0.915), (0.3, 0.89), (0.7, 0.86), (1.0, 0.815), (1.25, 0.805), (1.6, 0.78), (1.9, 0.745), (2.08, 0.69), (2.245, 0.47)],
        wr=[(-2.29, 0.45), (-2.0, 0.52), (-1.4, 0.52), (-0.7, 0.53), (-0.2, 0.54), (0.3, 0.53), (0.7, 0.48), (1.2, 0.46), (2.245, 0.42)],
        zr=[(-2.29, 0.87), (-2.0, 0.95), (-1.6, 0.99), (-1.2, 1.05), (-0.7, 1.16), (-0.25, 1.245), (0.1, 1.22), (0.4, 1.08), (0.7, 0.825), (1.0, 0.75), (1.5, 0.69), (1.9, 0.645), (2.1, 0.59), (2.245, 0.46)],
        zc=[(-2.29, 0.88), (-2.2, 0.925), (-2.0, 0.955), (-1.6, 1.0), (-1.2, 1.08), (-0.7, 1.20), (-0.25, 1.295), (0.1, 1.27), (0.4, 1.13), (0.7, 0.83), (1.0, 0.745), (1.5, 0.68), (1.9, 0.63), (2.1, 0.58), (2.245, 0.46)],
    ),
    mirrors=dict(x=0.60, y=0.97, z=0.915, size=(0.095, 0.075, 0.048), root=(0.64, 0.80, 0.86)),
    lenses=[(0.60, 0.615, (0.045, 0.112, 0.098))],
    wing=dict(x=-1.94, z=0.965, span=1.36, chord=0.30),
)

ROADSTER = dict(
    name='roadster', rear=-2.12, front=2.14, round_front=(0.40, 0.8, 0.33), round_rear=(0.16, 0.45, 0.58),
    wheelbase=2.60, track_f=1.66, track_r=1.66,
    wheel_f=(0.335, 0.245, 0.242), wheel_r=(0.352, 0.325, 0.254),
    rim='roadster',
    keys=dict(
        zb=[(-2.12, 0.34), (-1.8, 0.22), (-1.5, 0.15), (0, 0.12), (1.5, 0.13), (1.9, 0.15), (2.14, 0.22)],
        wl=[(-2.12, 0.78), (-1.3, 0.86), (0, 0.84), (1.3, 0.84), (2.14, 0.64)],
        w=[(-2.12, 0.90), (-1.8, 0.98), (-1.3, 1.00), (-0.5, 0.95), (0.4, 0.945), (1.25, 0.975), (1.8, 0.93), (2.14, 0.76)],
        zs=[(-2.12, 0.40), (-1.7, 0.28), (0, 0.22), (1.7, 0.24), (2.14, 0.30)],
        zm=[(-2.12, 0.60), (-1.3, 0.55), (0, 0.46), (1.3, 0.48), (2.14, 0.40)],
        wb=[(-2.12, 0.86), (-1.7, 0.94), (-1.3, 0.95), (-0.5, 0.86), (0.4, 0.85), (1.25, 0.90), (1.8, 0.84), (2.14, 0.66)],
        zbelt=[(-2.12, 0.78), (-1.7, 0.81), (-1.25, 0.815), (-0.5, 0.76), (0.4, 0.73), (1.0, 0.75), (1.3, 0.75), (1.7, 0.69), (2.0, 0.58), (2.14, 0.46)],
        wg=[(-2.12, 0.70), (-1.7, 0.80), (-1.25, 0.78), (-0.5, 0.70), (0.3, 0.72), (0.8, 0.74), (1.3, 0.76), (1.9, 0.68), (2.14, 0.50)],
        zg=[(-2.12, 0.81), (-1.7, 0.86), (-1.25, 0.875), (-0.5, 0.82), (0.3, 0.78), (0.8, 0.775), (1.1, 0.785), (1.3, 0.785), (1.6, 0.75), (1.9, 0.67), (2.14, 0.48)],
        wr=[(-2.12, 0.40), (-1.7, 0.52), (-1.2, 0.55), (-0.5, 0.58), (0.1, 0.58), (0.6, 0.52), (0.9, 0.45), (1.6, 0.42), (2.14, 0.32)],
        zr=[(-2.12, 0.80), (-1.7, 0.84), (-1.2, 0.93), (-0.6, 1.04), (-0.15, 1.08), (0.35, 1.00), (0.85, 0.72), (1.5, 0.645), (1.9, 0.60), (2.14, 0.48)],
        zc=[(-2.12, 0.80), (-1.9, 0.845), (-1.5, 0.90), (-1.0, 1.00), (-0.5, 1.085), (-0.15, 1.12), (0.3, 1.08), (0.6, 0.93), (0.9, 0.72), (1.5, 0.63), (1.9, 0.58), (2.14, 0.46)],
    ),
    mirrors=dict(x=0.66, y=1.0, z=0.81, size=(0.085, 0.06, 0.04), root=(0.72, 0.78, 0.76)),
    wing=None,
)


def make_mats():
    return dict(
        paint=material('paint', (0.6, 0.02, 0.02), 0.3, 0.3),
        well=material('well', (0.01, 0.01, 0.01), 0, 0.9),
        tire=material('tire', (0.02, 0.02, 0.02), 0, 0.85),
        rim=material('rim', (0.55, 0.55, 0.57), 1.0, 0.3),
        rim_dark=material('rim_dark', (0.03, 0.03, 0.03), 0.5, 0.6),
        disc=material('disc', (0.25, 0.25, 0.26), 1.0, 0.45),
        nut=material('nut', (0.8, 0.1, 0.1), 0.6, 0.35),
        caliper=material('caliper', (0.8, 0.6, 0.02), 0.2, 0.4),
        trim=material('trim', (0.02, 0.02, 0.02), 0.3, 0.45),
        mirror_glass=material('mirror_glass', (0.8, 0.8, 0.8), 1, 0.02),
        lens=material('lens', (0.9, 0.92, 0.95), 0.0, 0.02),
    )


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def build(spec, preview=False):
    reset()
    mats = make_mats()
    if spec['name'] == 'roadster':
        mats['caliper'] = material('caliper', (0.75, 0.05, 0.05), 0.2, 0.4)
    wf, wr_ = spec['wheel_f'], spec['wheel_r']
    xf, xr = spec['wheelbase'] / 2, -spec['wheelbase'] / 2
    # cutters start just inboard of each tyre's inner face; the inner cap of the
    # cylinder becomes the wheel-well liner
    spec['arches'] = [
        (xf, wf[0] + 0.04, spec['track_f'] / 2 - wf[1] / 2 - 0.03),
        (xr, wr_[0] + 0.04, spec['track_r'] / 2 - wr_[1] / 2 - 0.03),
    ]
    spec['arch_z'] = arch_z
    body = build_body(spec, mats)
    objs = [body]
    for (tag, x, (R, W, Rrim), tr) in (('F', xf, wf, spec['track_f']), ('R', xr, wr_, spec['track_r'])):
        for side, sname in ((1, 'L'), (-1, 'R')):
            loc = (x, side * tr / 2, R)
            objs.append(build_wheel('wheel_' + tag + sname, R, W, Rrim, spec['rim'], mats, side, loc))
            objs.append(build_caliper('caliper_' + tag + sname, Rrim, W, side, loc, mats['caliper']))
    m = spec['mirrors']
    for side, sname in ((1, 'L'), (-1, 'R')):
        objs.append(build_mirror('mirror_' + sname, (m['x'], side * m['y'], m['z']), m['size'], mats['paint'],
                                 (m['root'][0], side * m['root'][1], m['root'][2]), mats['trim']))
    for (ly, lz, radii) in spec.get('lenses', []):
        for side in (1, -1):
            objs.append(build_lens(body, 'lens', side * ly, lz, radii, mats['lens']))
    if spec['wing']:
        wg = build_wing(spec['wing'], mats)
        wg.location = (spec['wing']['x'], 0, spec['wing']['z'])
        objs.append(wg)
    path = os.path.join(OUT, spec['name'] + '.glb')
    bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', export_apply=True,
                              export_yup=True, export_normals=True, export_texcoords=False,
                              export_materials='EXPORT', export_draco_mesh_compression_enable=True,
                              export_draco_mesh_compression_level=7,
                              export_draco_position_quantization=16,
                              export_draco_normal_quantization=12)
    print('wrote', path, os.path.getsize(path) // 1024, 'KB')
    if preview: render_previews(spec['name'])


def render_previews(name):
    scn = bpy.context.scene
    scn.render.engine = 'CYCLES'; scn.cycles.samples = 24; scn.cycles.device = 'CPU'
    scn.render.resolution_x = 900; scn.render.resolution_y = 420
    world = bpy.data.worlds.new('w'); scn.world = world; world.use_nodes = True
    world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.8, 0.82, 0.85, 1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1.0
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); scn.collection.objects.link(cam)
    scn.camera = cam
    views = dict(side=((0, 12, 0.6), (math.pi / 2, 0, math.pi), 'ORTHO', 5.2),
                 front=((12, 0, 0.6), (math.pi / 2, 0, math.pi / 2), 'ORTHO', 2.6),
                 top=((0, 0, 12), (0, 0, 0), 'ORTHO', 5.2),
                 q34=((5.2, 4.2, 1.9), None, 'PERSP', 0))
    for v, (loc, rot, kind, scale) in views.items():
        cam.location = loc; cam.data.type = kind
        if kind == 'ORTHO': cam.data.ortho_scale = scale; cam.rotation_euler = rot
        else:
            d = Vector((0, 0, 0.5)) - Vector(loc)
            cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler(); cam.data.lens = 40
        scn.render.filepath = os.path.join(os.environ.get('PREVIEW_DIR', '/tmp'), f'{name}_{v}.png')
        bpy.ops.render.render(write_still=True)


if __name__ == '__main__':
    prev = '--preview' in sys.argv
    only = [a for a in sys.argv[1:] if a in ('911', 'roadster')]
    for s in (PORSCHE, ROADSTER):
        if not only or s['name'] in only:
            build(s, prev)
