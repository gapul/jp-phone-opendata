import CallKit
import Foundation
import PhoneDirectoryKit
import os

private let log = Logger(subsystem: "net.gapul.JPPhoneDirectory", category: "CallDirectory")

final class CallDirectoryHandler: CXCallDirectoryProvider {
    override func beginRequest(with context: CXCallDirectoryExtensionContext) {
        context.delegate = self

        // Every reload rebuilds the whole set: which lists are enabled can change
        // between runs, so there is no meaningful delta to apply.
        if context.isIncremental {
            context.removeAllIdentificationEntries()
        }

        let lists = DirectoryCatalog.openEnabled { id, error in
            log.error("""
                skipping \(id, privacy: .public): \
                \(error?.localizedDescription ?? "no file", privacy: .public)
                """)
        }

        let registered = DirectoryMerge.merge(lists) { number, label in
            context.addIdentificationEntry(withNextSequentialPhoneNumber: number, label: label)
        }
        log.info("registered \(registered, privacy: .public) from \(lists.count, privacy: .public) lists")

        context.completeRequest()
    }
}

extension CallDirectoryHandler: CXCallDirectoryExtensionContextDelegate {
    func requestFailed(for extensionContext: CXCallDirectoryExtensionContext, withError error: Error) {
        // iOS reports the reason here rather than to the container app, and the
        // usual reason is exceeding the extension's memory budget.
        log.error("request failed: \(error.localizedDescription, privacy: .public)")
    }
}
