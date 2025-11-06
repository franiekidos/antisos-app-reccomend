
pkgname=antisos-store
pkgver=1.0.0
pkgrel=1
pkgdesc="A simple tool to select applications and generate a unified installation script."
arch=('any')
url="https://github.com/antis-build"
license=('MIT')
depends=('gtk4' 'libadwaita')
makedepends=('python-pyinstaller' 'python-gobject')
optdepends=(
    'paru: for AUR package installation'
    'yay: for AUR package installation'
    'flatpak: for Flatpak support'
    'snapd: for Snap support'
    'nix: for Nix support'
)
# For local builds, ensure these files are in the same directory as the PKGBUILD
source=("antisos-app-recc.py"
        "antisos-store.desktop")

sha256sums=('SKIP'
            'SKIP')

build() {
    # Compile the python script into a single executable using PyInstaller
    pyinstaller --noconfirm --onefile --name "$pkgname" antisos-app-recc
}

package() {
    # Install the compiled executable from the dist/ directory
    install -d "$pkgdir/usr/bin"
    install -m755 "dist/$pkgname" "$pkgdir/usr/bin/$pkgname"

    # Install the desktop entry
    install -d "$pkgdir/usr/share/applications"
    install -m644 "$pkgname.desktop" "$pkgdir/usr/share/applications/$pkgname.desktop"
}