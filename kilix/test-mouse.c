/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "osdep/terminal-mouse.h"

int main(void)
{
    struct terminal_mouse_event e;
    const unsigned char valid[] = "\033[<20;300;500M";
    for (size_t n = 0; n < sizeof(valid) - 1; n++)
        assert(terminal_mouse_parse(valid, n, &e) == 0);
    assert(terminal_mouse_parse(valid, sizeof(valid) - 1, &e) == sizeof(valid) - 1);
    assert(e.button == 20 && e.x == 300 && e.y == 500 && !e.release);
    const unsigned char release[] = "\033[<0;1;2m";
    assert(terminal_mouse_parse(release, sizeof(release) - 1, &e) > 0);
    assert(e.release && e.x == 1 && e.y == 2);
    const unsigned char origin[] = "\033[<0;0;0M";
    assert(terminal_mouse_parse(origin, sizeof(origin) - 1, &e) > 0);
    assert(e.x == 0 && e.y == 0);
    const char *bad[] = {"\033[<;1;1M",
        "\033[<0;1;2;3M", "\033[<0;2147483648;1M", "\033[<0;-1;2M",
        "\033[<0;1;2X", "\033[<0;1;9999999999999999999999999M"};
    for (size_t i = 0; i < sizeof(bad) / sizeof(*bad); i++)
        assert(terminal_mouse_parse((const unsigned char *)bad[i], strlen(bad[i]), &e)
               == -(int)strlen(bad[i]));
    unsigned char oversized[80];
    memset(oversized, '9', sizeof(oversized));
    memcpy(oversized, "\033[<", 3);
    assert(terminal_mouse_parse(oversized, sizeof(oversized), &e) == -64);
    const unsigned char chained[] = "\033[<0;4;5M\033[<0;4;5m";
    int used = terminal_mouse_parse(chained, sizeof(chained) - 1, &e);
    assert(used == 9 && !e.release);
    assert(terminal_mouse_parse(chained + used, sizeof(chained) - 1 - used, &e) == 9);
    assert(e.release);
    puts("PASS SGR mouse: fragmentation, coordinates, modifiers, release, malformed bounds");
}
