import Foundation
import SwiftUI

final class AppSettingsStore: ObservableObject {
    @AppStorage("officeBaseURL") var officeBaseURL: String = "http://127.0.0.1:8090"
    @AppStorage("notificationsEnabled") var notificationsEnabled: Bool = false

    func normalizedURL(_ raw: String) -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.hasSuffix("/") {
            return String(trimmed.dropLast())
        }
        return trimmed
    }

    var officeDashboardURL: URL? { URL(string: normalizedURL(officeBaseURL)) }
    var officeBoreholeURL: URL? {
        guard let base = officeDashboardURL else { return nil }
        return base.appending(path: "borehole")
    }
}
