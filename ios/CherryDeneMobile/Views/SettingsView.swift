import SwiftUI
import UserNotifications

struct SettingsView: View {
    @EnvironmentObject private var settings: AppSettingsStore
    @EnvironmentObject private var notifications: NotificationManager

    var body: some View {
        NavigationStack {
            Form {
                Section("Dashboard URLs") {
                    TextField("Office dashboard URL", text: $settings.officeBaseURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()

                    TextField("Shed controller URL", text: $settings.shedBaseURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()

                    TextField("Bore hole controller URL", text: $settings.boreholeBaseURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                }

                Section("Controller Defaults") {
                    Stepper(value: $settings.defaultShedNumber, in: 1...20) {
                        Text("Default shed: \(settings.defaultShedNumber)")
                    }
                }

                Section("Notifications") {
                    Toggle("Enable alarm notifications later", isOn: $settings.notificationsEnabled)

                    HStack {
                        Text("Permission")
                        Spacer()
                        Text(permissionText)
                            .foregroundStyle(.secondary)
                    }

                    Button("Request Notification Permission") {
                        Task {
                            _ = await notifications.requestPermission()
                        }
                    }
                }

                Section("About") {
                    Text("This app is a native SwiftUI shell around the Cherry Dene office, shed, bore hole, and farm health dashboards.")
                    Text("Real alarm push notifications need backend and APNs work later.")
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
        }
    }

    private var permissionText: String {
        switch notifications.authorizationStatus {
        case .authorized, .provisional, .ephemeral:
            return "Allowed"
        case .denied:
            return "Denied"
        case .notDetermined:
            return "Not requested"
        @unknown default:
            return "Unknown"
        }
    }
}
