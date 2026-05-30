: type-pstr
    dup load swap 1 +
    swap 0 do
        dup i + load write-char
    loop
    drop
;

: main
    s"Hello, World!" type-pstr
;
