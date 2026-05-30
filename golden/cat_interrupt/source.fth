variable count

:interrupt on-input
    read-char write-char
    count load 1 + count store
;

: main
    ei
    begin
        count load 3 =
    until
;
