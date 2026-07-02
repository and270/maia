# nix/tui.nix — Hermes TUI (Ink/React) compiled with tsc and bundled
{ pkgs, hermesNpmLib, ... }:
let
  src = ../ui-tui;
  npmDeps = pkgs.fetchNpmDeps {
    inherit src;
    hash = "sha256-MLcLhjTF6dgdvNBtJWzo8Nh19eNh/ZitD2b07nm61Tc=";
  };

  npm = hermesNpmLib.mkNpmPassthru { folder = "ui-tui"; attr = "tui"; pname = "maia-tui"; };

  packageJson = builtins.fromJSON (builtins.readFile (src + "/package.json"));
  version = packageJson.version;
in
pkgs.buildNpmPackage (npm // {
  pname = "maia-tui";
  inherit src npmDeps version;

  doCheck = false;
  npmFlags = [ "--legacy-peer-deps" ];

  installPhase = ''
    runHook preInstall

    mkdir -p $out/lib/maia-tui

    cp -r dist $out/lib/maia-tui/dist

    # runtime node_modules
    cp -r node_modules $out/lib/maia-tui/node_modules

    # @maia/ink is a file: dependency, we need to copy it in fr
    rm -f $out/lib/maia-tui/node_modules/@maia/ink
    cp -r packages/maia-ink $out/lib/maia-tui/node_modules/@maia/ink

    # package.json needed for "type": "module" resolution
    cp package.json $out/lib/maia-tui/

    runHook postInstall
  '';
})
