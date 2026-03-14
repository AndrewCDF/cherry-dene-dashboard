import Foundation
import SwiftUI

final class AppSettingsStore: ObservableObject {
    @AppStorage("officeBaseURL") var officeBaseURL: String = "http://127.0.0.1:8090"
    @AppStorage("shedBaseURL") var shedBaseURL: String = "http://127.0.0.1:8091"
    @AppStorage("boreholeBaseURL") var boreholeBaseURL: String = "http://127.0.0.1:8092"
    @AppStorage("defaultShedNumber") var defaultShedNumber: Int = 1
    @AppStorage("notificationsEnabled") var notificationsEnabled: Bool = false

    func normalizedURL(_ raw: String) -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.hasSuffix("/") {
            return String(trimmed.dropLast())
        }
        return trimmed
    }

    var officeDashboardURL: URL? { URL(string: normalizedURL(officeBaseURL)) }
    var officeFarmHealthURL: URL? { URL(string: normalizedURL(officeBaseURL) + "/farm-health") }
    var shedControllerURL: URL? { URL(string: normalizedURL(shedBaseURL)) }
    var boreholeControllerURL: URL? { URL(string: normalizedURL(boreholeBaseURL)) }
}
