PREFIX = /usr
KEYRING = ashlaros

install:
	install -dm755 $(DESTDIR)$(PREFIX)/share/pacman/keyrings/
	install -m0644 $(KEYRING).gpg $(DESTDIR)$(PREFIX)/share/pacman/keyrings/
	install -m0644 $(KEYRING)-trusted $(DESTDIR)$(PREFIX)/share/pacman/keyrings/
	install -m0644 $(KEYRING)-revoked $(DESTDIR)$(PREFIX)/share/pacman/keyrings/

uninstall:
	rm -f $(DESTDIR)$(PREFIX)/share/pacman/keyrings/$(KEYRING){.gpg,-trusted,-revoked}
	rmdir -p --ignore-fail-on-non-empty $(DESTDIR)$(PREFIX)/share/pacman/keyrings/
