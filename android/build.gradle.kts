// Build with a JDK 21, not the one Android Studio bundles: current Studio ships
// a JBR 25, which Gradle 8.11 refuses. On this machine:
//
//   export JAVA_HOME=$(nix build nixpkgs#jdk21 --no-link --print-out-paths)
//   export ANDROID_HOME="$HOME/Library/Android/sdk"
//   ./gradlew test assembleDebug
//
// The SDK itself is not declared in nix — Android Studio owns it, the way it
// owns its own updates.
plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
}
