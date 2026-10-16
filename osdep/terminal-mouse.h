/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Bounded SGR mouse parser. Coordinates remain one-based terminal cells. */
#ifndef MP_TERMINAL_MOUSE_H
#define MP_TERMINAL_MOUSE_H
#include <stdbool.h>
#include <limits.h>
#include <stddef.h>
struct terminal_mouse_event {
    unsigned button, x, y;
    bool release;
};
/* Positive: consumed event; zero: incomplete; negative: malformed bytes consumed. */
static inline int terminal_mouse_parse(const unsigned char *s, size_t n,
                                       struct terminal_mouse_event *out)
{
    unsigned values[3] = {0};
    unsigned field = 0;
    bool digits = false, invalid = false;
    if (n < 3)
        return 0;
    if (s[0] != 27 || s[1] != '[' || s[2] != '<')
        return -1;
    for (size_t i = 3; i < n && i < 64; ++i) {
        unsigned c = s[i];
        if (c >= 0x40 && c <= 0x7e) {
            if (invalid || field != 2 || !digits || !values[1] || !values[2] ||
                (c != 'M' && c != 'm'))
                return -(int)(i + 1);
            *out = (struct terminal_mouse_event){values[0], values[1], values[2], c == 'm'};
            return i + 1;
        }
        if (c == ';' && field < 2 && digits) {
            field++;
            digits = false;
        } else if (c >= '0' && c <= '9') {
            unsigned digit = c - '0';
            if (values[field] > (INT_MAX - digit) / 10u)
                invalid = true;
            else
                values[field] = values[field] * 10u + digit;
            digits = true;
        } else {
            invalid = true;
        }
    }
    return n >= 64 ? -64 : 0;
}
#endif
