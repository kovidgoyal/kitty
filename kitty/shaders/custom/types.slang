#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.



public struct KittyCustomShaderData {
    public uniform uint timestamp;
    public uniform Sampler2D backbuffer;

    public float2 texcoord;
}
