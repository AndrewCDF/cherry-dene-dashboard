import SwiftUI

@main
struct CherryDeneMobileApp: App {
    @StateObject private var settings = AppSettingsStore()

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .environmentObject(settings)
        }
    }
}
