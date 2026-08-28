// swift-tools-version: 5.9
import PackageDescription

// The list engine is kept free of CallKit so it builds and tests on the host,
// where `swift test` can exercise the merge without a device.
let package = Package(
    name: "PhoneDirectoryKit",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "PhoneDirectoryKit", targets: ["PhoneDirectoryKit"]),
    ],
    targets: [
        .target(name: "PhoneDirectoryKit"),
        .testTarget(name: "PhoneDirectoryKitTests", dependencies: ["PhoneDirectoryKit"]),
    ]
)
